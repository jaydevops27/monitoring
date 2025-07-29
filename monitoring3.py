#!/usr/bin/env python3

import json
import subprocess
import datetime
import csv
import logging
import sys
import os
import time
import yaml
from typing import List, Dict, Any, Optional
import argparse
from pathlib import Path
import re
import tempfile
import requests  # for webhook/Slack integration
from tabulate import tabulate

def get_output_directory():
    """Get appropriate output directory for CI/local environments"""
    if os.environ.get('CI'):
        output_dir = os.path.join(os.getcwd(), 'monitoring-output')
        os.makedirs(output_dir, exist_ok=True)
        return output_dir
    else:
        return tempfile.gettempdir()

OUTPUT_DIR = get_output_directory()
log_file_path = os.path.join(OUTPUT_DIR, 'service_monitor.log')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file_path),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

logger.info(f"Output directory: {OUTPUT_DIR}")
if os.environ.get('CI'):
    logger.info("Running in CI environment - artifacts will be saved to monitoring-output/")

class ServiceDiagnosticEngine:
    """Diagnostic engine focused on service health and availability"""
    
    def __init__(self):
        # Service-specific error patterns and solutions
        self.error_patterns = {
            r'OOMKilled|out of memory|memory limit exceeded': {
                'category': 'MEMORY',
                'severity': 'high',
                'suggestion': 'Increase memory limits in deployment/statefulset',
                'action': 'kubectl patch deployment {deployment} -n {namespace} -p \'{"spec":{"template":{"spec":{"containers":[{"name":"{container}","resources":{"limits":{"memory":"1Gi"}}}]}}}}\''
            },
            r'CrashLoopBackOff|Error: failed to start container|exit code 1': {
                'category': 'SERVICE_CRASH',
                'severity': 'high',
                'suggestion': 'Service startup failing - check configuration and dependencies',
                'action': 'kubectl logs {pod} -n {namespace} --previous && kubectl describe pod {pod} -n {namespace}'
            },
            r'ImagePullBackOff|ErrImagePull|pull access denied|manifest unknown': {
                'category': 'IMAGE_UNAVAILABLE',
                'severity': 'high',
                'suggestion': 'Service image cannot be pulled - verify image exists and registry access',
                'action': 'kubectl describe pod {pod} -n {namespace} | grep -A 10 Events'
            },
            r'connection refused|dial tcp.*refused|network.*timeout': {
                'category': 'SERVICE_CONNECTIVITY',
                'severity': 'medium',
                'suggestion': 'Service connectivity issues - check ports and internal networking',
                'action': 'kubectl get svc -n {namespace} && kubectl get endpoints -n {namespace}'
            },
            r'liveness probe failed|readiness probe failed|health check failed': {
                'category': 'HEALTH_CHECK',
                'severity': 'medium',
                'suggestion': 'Service health checks failing - review probe configuration',
                'action': 'kubectl get pod {pod} -n {namespace} -o yaml | grep -A 15 "livenessProbe\\|readinessProbe"'
            },
            r'database.*connection|db.*timeout|sql.*error|redis.*connection': {
                'category': 'DATABASE_CONNECTION',
                'severity': 'high',
                'suggestion': 'Database connectivity issues - check service dependencies',
                'action': 'kubectl get pods -n {namespace} -l app=database && kubectl logs -l app=database -n {namespace}'
            },
            r'permission denied|forbidden|unauthorized|access denied': {
                'category': 'SERVICE_PERMISSIONS',
                'severity': 'medium',
                'suggestion': 'Service permission issues - check RBAC and service accounts',
                'action': 'kubectl describe serviceaccount -n {namespace} && kubectl get rolebindings -n {namespace}'
            },
            r'port.*already in use|address already in use|bind.*failed': {
                'category': 'PORT_CONFLICT',
                'severity': 'medium',
                'suggestion': 'Port conflicts in service configuration',
                'action': 'kubectl get svc -n {namespace} -o wide'
            }
        }

    def analyze_service_logs(self, namespace: str, pod_name: str, lines: int = 50) -> Dict[str, Any]:
        """Analyze service logs for service-specific issues"""
        analysis = {
            'service_issues': [],
            'recommendations': [],
            'severity': 'low',
            'service_health_score': 100
        }
        
        try:
            # Get current and previous logs
            current_logs = self._get_logs(namespace, pod_name, lines, previous=False)
            previous_logs = self._get_logs(namespace, pod_name, lines, previous=True)
            
            all_logs = f"{previous_logs}\n{current_logs}"
            
            if all_logs and all_logs != "Could not retrieve logs":
                analysis = self._analyze_service_log_content(all_logs, namespace, pod_name)
                
        except Exception as e:
            logger.error(f"Error analyzing service logs for {namespace}/{pod_name}: {e}")
            
        return analysis

    def _get_logs(self, namespace: str, pod_name: str, lines: int, previous: bool = False) -> str:
        """Get service logs"""
        try:
            command = ["kubectl", "logs", pod_name, "-n", namespace, "--tail", str(lines)]
            if previous:
                command.append("--previous")
                
            result = subprocess.run(command, capture_output=True, text=True, timeout=15)
            
            if result.returncode == 0 and result.stdout:
                return result.stdout
            elif previous and "previous terminated container" in result.stderr:
                return ""
            else:
                return "Could not retrieve logs"
                
        except subprocess.TimeoutExpired:
            return "Log retrieval timed out"
        except Exception as e:
            return f"Error getting logs: {e}"

    def _analyze_service_log_content(self, logs: str, namespace: str, pod_name: str) -> Dict[str, Any]:
        """Analyze logs for service-specific patterns"""
        analysis = {
            'service_issues': [],
            'recommendations': [],
            'severity': 'low',
            'service_health_score': 100
        }
        
        log_lines = logs.split('\n')
        error_lines = [line for line in log_lines if any(keyword in line.lower() 
                      for keyword in ['error', 'exception', 'failed', 'panic', 'fatal', 'crash'])]
        
        max_severity_score = 0
        health_deduction = 0
        
        # Analyze against service-specific patterns
        for pattern, config in self.error_patterns.items():
            matches = re.findall(pattern, logs, re.IGNORECASE)
            if matches:
                severity_score = {'low': 1, 'medium': 2, 'high': 3}[config['severity']]
                max_severity_score = max(max_severity_score, severity_score)
                health_deduction += len(matches) * 10  # Deduct 10 points per issue
                
                issue = {
                    'category': config['category'],
                    'matches': len(matches),
                    'severity': config['severity'],
                    'suggestion': config['suggestion'],
                    'action': config['action'].format(
                        pod=pod_name, 
                        namespace=namespace,
                        container=pod_name.split('-')[0],  # Basic container name guess
                        deployment=pod_name.rsplit('-', 2)[0]  # Basic deployment name guess
                    )
                }
                analysis['service_issues'].append(issue)
        
        # Calculate service health score
        analysis['service_health_score'] = max(0, 100 - health_deduction)
        
        # Set overall severity
        severity_map = {0: 'low', 1: 'low', 2: 'medium', 3: 'high'}
        analysis['severity'] = severity_map[max_severity_score]
        
        # Generate service-specific recommendations
        analysis['recommendations'] = self._generate_service_recommendations(
            analysis['service_issues'], namespace, pod_name
        )
        
        return analysis

    def _generate_service_recommendations(self, issues: List[Dict], namespace: str, pod_name: str) -> List[Dict[str, str]]:
        """Generate service-focused recommendations"""
        recommendations = []
        
        # Group issues by category
        issue_categories = {}
        for issue in issues:
            category = issue['category']
            if category not in issue_categories:
                issue_categories[category] = []
            issue_categories[category].append(issue)
        
        # Generate specific service recommendations
        for category, category_issues in issue_categories.items():
            if category == 'SERVICE_CRASH':
                recommendations.append({
                    'priority': 'CRITICAL',
                    'title': f'Service {pod_name.split("-")[0]} is crashing',
                    'description': 'Service cannot start properly',
                    'immediate_action': f"kubectl describe pod {pod_name} -n {namespace}",
                    'follow_up': f"kubectl logs {pod_name} -n {namespace} --previous",
                    'long_term_fix': 'Review service configuration, environment variables, and startup dependencies'
                })
            
            elif category == 'MEMORY':
                recommendations.append({
                    'priority': 'HIGH',
                    'title': f'Service {pod_name.split("-")[0]} needs more memory',
                    'description': 'Service is running out of memory',
                    'immediate_action': f"kubectl top pod {pod_name} -n {namespace}",
                    'follow_up': f"kubectl get pod {pod_name} -n {namespace} -o yaml | grep -A 5 resources",
                    'long_term_fix': 'Increase memory limits or optimize application memory usage'
                })
            
            elif category == 'SERVICE_CONNECTIVITY':
                recommendations.append({
                    'priority': 'HIGH',
                    'title': f'Service {pod_name.split("-")[0]} connectivity issues',
                    'description': 'Service cannot connect to dependencies',
                    'immediate_action': f"kubectl get svc -n {namespace}",
                    'follow_up': f"kubectl get endpoints -n {namespace}",
                    'long_term_fix': 'Verify service discovery, DNS resolution, and network policies'
                })
                
            elif category == 'DATABASE_CONNECTION':
                recommendations.append({
                    'priority': 'CRITICAL',
                    'title': f'Service {pod_name.split("-")[0]} database issues',
                    'description': 'Cannot connect to database dependencies',
                    'immediate_action': f"kubectl get pods -n {namespace} | grep -E 'db|database|postgres|mysql|mongo'",
                    'follow_up': f"kubectl logs {pod_name} -n {namespace} | grep -i database",
                    'long_term_fix': 'Check database service health, credentials, and connection strings'
                })
        
        return recommendations

    def analyze_service_availability(self, namespace: str, service_pods: List[Dict]) -> Dict[str, Any]:
        """Analyze overall service availability within namespace"""
        availability_analysis = {
            'services_detected': {},
            'availability_score': 100,
            'critical_services_down': [],
            'degraded_services': []
        }
        
        # Group pods by service (based on common prefixes/labels)
        services = {}
        for pod in service_pods:
            pod_name = pod['metadata']['name']
            # Extract service name (everything before the first hash/random suffix)
            service_name = re.match(r'^([^-]+-[^-]+)', pod_name)
            if service_name:
                service_name = service_name.group(1)
            else:
                service_name = pod_name.split('-')[0]
            
            if service_name not in services:
                services[service_name] = []
            services[service_name].append(pod)
        
        # Analyze each service
        for service_name, pods in services.items():
            total_pods = len(pods)
            running_pods = len([p for p in pods if p['status'].get('phase') == 'Running'])
            ready_pods = len([p for p in pods if self._is_pod_ready(p)])
            
            availability_pct = (ready_pods / total_pods) * 100 if total_pods > 0 else 0
            
            service_status = {
                'total_pods': total_pods,
                'running_pods': running_pods,
                'ready_pods': ready_pods,
                'availability_percentage': availability_pct,
                'status': 'healthy' if availability_pct >= 80 else 'degraded' if availability_pct >= 50 else 'critical'
            }
            
            availability_analysis['services_detected'][service_name] = service_status
            
            # Track problematic services
            if availability_pct < 50:
                availability_analysis['critical_services_down'].append(service_name)
            elif availability_pct < 80:
                availability_analysis['degraded_services'].append(service_name)
        
        # Calculate overall namespace availability
        if services:
            total_availability = sum([s['availability_percentage'] for s in availability_analysis['services_detected'].values()])
            availability_analysis['availability_score'] = total_availability / len(services)
        
        return availability_analysis

    def _is_pod_ready(self, pod: Dict) -> bool:
        """Check if pod is ready for service"""
        conditions = pod.get('status', {}).get('conditions', [])
        for condition in conditions:
            if condition.get('type') == 'Ready' and condition.get('status') == 'True':
                return True
        return False


class NamespaceServiceMonitor:
    """Service-focused monitoring for namespace owners"""
    
    def __init__(
        self,
        namespaces: List[str],
        restart_threshold: int = 1,
        config: Dict[str, Any] = None,
        label_selector: Optional[str] = None,
    ):
        self.namespaces = namespaces
        self.restart_threshold = restart_threshold
        self.config = config or {}
        self.alerts = []
        self.previous_state = {}
        self.diagnostic_engine = ServiceDiagnosticEngine()

        self.output_dir = OUTPUT_DIR
        self.label_selector = label_selector

        # Service-focused statistics
        self.statistics = {
            "scan_start_time": datetime.datetime.now().isoformat(),
            "total_namespaces_checked": 0,
            "accessible_namespaces": 0,
            "inaccessible_namespaces": 0,
            "total_services_evaluated": 0,
            "total_pods_evaluated": 0,
            "total_containers_evaluated": 0,
            "services_healthy": 0,
            "services_degraded": 0,
            "services_critical": 0,
            "pods_with_restarts": 0,
            "pods_above_threshold": 0,
            "new_service_issues": 0,
            "repeated_service_issues": 0,
            "namespace_details": {},
            "service_availability": {},
            "environment": {
                "ci": os.environ.get('CI', False),
                "gitlab_ci": os.environ.get('GITLAB_CI', False),
                "job_name": os.environ.get('CI_JOB_NAME', 'local'),
                "pipeline_id": os.environ.get('CI_PIPELINE_ID', 'local'),
                "output_directory": self.output_dir
            }
        }

        self.load_previous_state()

    def load_previous_state(self):
        """Load previous service monitoring state"""
        state_file = self.config.get('state_file', os.path.join(self.output_dir, 'service_monitor_state.json'))
        try:
            if os.path.exists(state_file):
                with open(state_file, 'r') as f:
                    self.previous_state = json.load(f)
                logger.info(f"Loaded previous service state from {state_file}")
        except Exception as e:
            logger.warning(f"Could not load previous state: {e}")
            self.previous_state = {}

    def save_current_state(self):
        """Save current service monitoring state"""
        state_file = self.config.get('state_file', os.path.join(self.output_dir, 'service_monitor_state.json'))
        current_state = {
            "last_run": datetime.datetime.now().isoformat(),
            "service_restart_counts": {},
            "service_availability": self.statistics["service_availability"],
            "alerts": self.alerts,
            "environment": self.statistics["environment"]
        }
        
        # Save service restart counts for comparison
        for namespace in self.namespaces:
            pods = self.get_pods_in_namespace(namespace)
            for pod in pods:
                pod_key = f"{namespace}/{pod['metadata']['name']}"
                restart_info = self.extract_restart_info(pod)
                current_state["service_restart_counts"][pod_key] = restart_info["max_restarts"]
        
        try:
            with open(state_file, 'w') as f:
                json.dump(current_state, f, indent=2)
            logger.info(f"Saved current service state to {state_file}")
        except Exception as e:
            logger.error(f"Could not save state: {e}")

    def check_cluster_connectivity(self) -> bool:
        """Basic connectivity check"""
        try:
            subprocess.run(
                ["kubectl", "cluster-info"],
                capture_output=True,
                check=True,
                timeout=10
            )
            return True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            logger.error("Cannot connect to Kubernetes cluster. Check your kubeconfig.")
            return False

    def run_kubectl_command(self, command: List[str]) -> Dict[str, Any]:
        """Execute kubectl commands with timeout"""
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=True,
                timeout=30
            )
            return json.loads(result.stdout) if result.stdout else {}
        except subprocess.TimeoutExpired:
            logger.error(f"kubectl command timed out: {' '.join(command)}")
            return {}
        except subprocess.CalledProcessError as e:
            logger.error(f"kubectl command failed: {' '.join(command)}")
            logger.error(f"Error: {e.stderr}")
            return {}
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON output: {e}")
            return {}

    def get_pods_in_namespace(self, namespace: str) -> List[Dict[str, Any]]:
        """Get pods in namespace"""
        command = ["kubectl", "get", "pods", "-n", namespace, "-o", "json"]
        if self.label_selector:
            command += ["-l", self.label_selector]
        result = self.run_kubectl_command(command)
        return result.get("items", [])

    def get_services_in_namespace(self, namespace: str) -> List[Dict[str, Any]]:
        """Get services in namespace"""
        command = ["kubectl", "get", "services", "-n", namespace, "-o", "json"]
        result = self.run_kubectl_command(command)
        return result.get("items", [])

    def get_deployments_in_namespace(self, namespace: str) -> List[Dict[str, Any]]:
        """Get deployments in namespace"""
        command = ["kubectl", "get", "deployments", "-n", namespace, "-o", "json"]
        result = self.run_kubectl_command(command)
        return result.get("items", [])

    def get_events_for_pod(self, namespace: str, pod_name: str) -> List[Dict[str, Any]]:
        """Get events for specific pod"""
        command = ["kubectl", "get", "events", "-n", namespace,
                  "--field-selector", f"involvedObject.name={pod_name}",
                  "-o", "json"]
        result = self.run_kubectl_command(command)
        return result.get("items", [])

    def is_pod_filtered(self, pod: Dict[str, Any]) -> bool:
        """Check if pod should be filtered out"""
        if not self.config.get('filters'):
            return False
        filters = self.config['filters']
        pod_name = pod["metadata"]["name"]
        exclude_patterns = filters.get('exclude_pods_pattern', [])
        for pattern in exclude_patterns:
            if re.match(pattern, pod_name):
                logger.debug(f"Pod {pod_name} excluded by pattern {pattern}")
                return True
        max_age_hours = filters.get('max_pod_age_hours')
        if max_age_hours:
            creation_time = datetime.datetime.fromisoformat(
                pod["metadata"]["creationTimestamp"].replace('Z', '+00:00')
            )
            age = datetime.datetime.now(datetime.timezone.utc) - creation_time
            if age.total_seconds() < max_age_hours * 3600:
                logger.debug(f"Pod {pod_name} too young, skipping")
                return True
        if filters.get('include_only_running'):
            if pod["status"].get("phase") != "Running":
                return True
        return False

    def extract_restart_info(self, pod: Dict[str, Any]) -> Dict[str, Any]:
        """Extract service restart information"""
        pod_name = pod["metadata"]["name"]
        namespace = pod["metadata"]["namespace"]
        restart_info = {
            "pod_name": pod_name,
            "namespace": namespace,
            "node": pod["spec"].get("nodeName", "Unknown"),
            "phase": pod["status"].get("phase", "Unknown"),
            "creation_time": pod["metadata"].get("creationTimestamp", "Unknown"),
            "containers": [],
            "service_name": self._extract_service_name(pod_name)
        }
        container_statuses = pod["status"].get("containerStatuses", [])
        max_restarts = 0
        for container in container_statuses:
            restart_count = container.get("restartCount", 0)
            max_restarts = max(max_restarts, restart_count)
            container_info = {
                "name": container["name"],
                "restart_count": restart_count,
                "ready": container.get("ready", False),
                "state": list(container.get("state", {}).keys())[0] if container.get("state") else "Unknown",
                "image": container.get("image", "Unknown")
            }
            last_state = container.get("lastState", {})
            if "terminated" in last_state:
                container_info["last_termination_reason"] = last_state["terminated"].get("reason", "Unknown")
                container_info["last_termination_time"] = last_state["terminated"].get("finishedAt", "Unknown")
                container_info["exit_code"] = last_state["terminated"].get("exitCode", "Unknown")
            restart_info["containers"].append(container_info)
        restart_info["max_restarts"] = max_restarts
        pod_key = f"{namespace}/{pod_name}"
        previous_restarts = self.previous_state.get("service_restart_counts", {}).get(pod_key, 0)
        restart_info["is_new_issue"] = restart_info["max_restarts"] > previous_restarts
        restart_info["previous_restart_count"] = previous_restarts
        return restart_info

    def _extract_service_name(self, pod_name: str) -> str:
        """Extract service name from pod name"""
        # Common patterns: service-name-deployment-hash-pod, service-name-hash
        match = re.match(r'^([^-]+-[^-]+)', pod_name)
        if match:
            return match.group(1)
        return pod_name.split('-')[0]

    def check_namespace_services(self, namespace: str) -> List[Dict[str, Any]]:
        """Check services in namespace for issues"""
        logger.info(f"Checking services in namespace: {namespace}")
        alerts = []
        namespace_stats = {
            "accessible": False,
            "services_count": 0,
            "pods_count": 0,
            "containers_count": 0,
            "services_healthy": 0,
            "services_degraded": 0,
            "services_critical": 0,
            "pods_with_restarts": 0,
            "pods_above_threshold": 0,
            "filtered_pods": 0,
            "service_availability_score": 100
        }
        
        self.statistics["total_namespaces_checked"] += 1
        
        # Check namespace accessibility
        try:
            subprocess.run(
                ["kubectl", "get", "namespace", namespace],
                capture_output=True,
                check=True,
                timeout=10
            )
            namespace_stats["accessible"] = True
            self.statistics["accessible_namespaces"] += 1
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            logger.warning(f"Namespace {namespace} not found or not accessible")
            self.statistics["inaccessible_namespaces"] += 1
            self.statistics["namespace_details"][namespace] = namespace_stats
            return alerts

        # Get namespace resources
        pods = self.get_pods_in_namespace(namespace)
        services = self.get_services_in_namespace(namespace)
        deployments = self.get_deployments_in_namespace(namespace)

        namespace_stats["pods_count"] = len(pods)
        namespace_stats["services_count"] = len(services)
        self.statistics["total_pods_evaluated"] += len(pods)

        # Analyze service availability
        service_availability = self.diagnostic_engine.analyze_service_availability(namespace, pods)
        namespace_stats["service_availability_score"] = service_availability["availability_score"]
        
        # Count service health status
        for service_name, service_info in service_availability["services_detected"].items():
            if service_info["status"] == "healthy":
                namespace_stats["services_healthy"] += 1
                self.statistics["services_healthy"] += 1
            elif service_info["status"] == "degraded":
                namespace_stats["services_degraded"] += 1
                self.statistics["services_degraded"] += 1
            else:  # critical
                namespace_stats["services_critical"] += 1
                self.statistics["services_critical"] += 1

        self.statistics["total_services_evaluated"] += len(service_availability["services_detected"])
        self.statistics["service_availability"][namespace] = service_availability

        # Check individual pods for restart issues
        for pod in pods:
            if self.is_pod_filtered(pod):
                namespace_stats["filtered_pods"] += 1
                continue
                
            restart_info = self.extract_restart_info(pod)
            container_count = len(restart_info["containers"])
            namespace_stats["containers_count"] += container_count
            self.statistics["total_containers_evaluated"] += container_count
            
            if restart_info["max_restarts"] > 0:
                namespace_stats["pods_with_restarts"] += 1
                self.statistics["pods_with_restarts"] += 1
                
            if restart_info["max_restarts"] > self.restart_threshold:
                namespace_stats["pods_above_threshold"] += 1
                self.statistics["pods_above_threshold"] += 1
                
                # Enhanced service analysis
                events = self.get_events_for_pod(namespace, restart_info["pod_name"])
                log_analysis = self.diagnostic_engine.analyze_service_logs(
                    namespace, restart_info["pod_name"], lines=100
                )
                
                # Calculate service impact severity
                severity = self.calculate_service_impact_severity(restart_info, log_analysis, service_availability)
                
                alert = {
                    "timestamp": datetime.datetime.now().isoformat(),
                    "namespace": namespace,
                    "service_name": restart_info["service_name"],
                    "pod_name": restart_info["pod_name"],
                    "restart_count": restart_info["max_restarts"],
                    "previous_restart_count": restart_info["previous_restart_count"],
                    "is_new_issue": restart_info["is_new_issue"],
                    "status": restart_info["phase"],
                    "node": restart_info["node"],
                    "creation_time": restart_info["creation_time"],
                    "containers": restart_info["containers"],
                    "recent_events": events[-3:] if events else [],
                    "severity": severity,
                    "log_analysis": log_analysis,
                    "service_health_score": log_analysis.get("service_health_score", 100),
                    "recommendations": log_analysis.get("recommendations", [])
                }
                
                alerts.append(alert)
                
                if alert['is_new_issue']:
                    self.statistics["new_service_issues"] += 1
                else:
                    self.statistics["repeated_service_issues"] += 1
                
                # Service-focused logging - PROFESSIONAL FORMAT
                severity_text = alert['severity'].upper()
                logger.warning(
                    f"SERVICE ISSUE [{severity_text}]: {restart_info['service_name']} "
                    f"pod {restart_info['pod_name']} in {namespace} has {restart_info['max_restarts']} restarts "
                    f"(health score: {alert['service_health_score']}/100)"
                )
                
                # Send webhook for service issues
                webhook_url = self.config.get('webhook_url')
                if webhook_url and alert['severity'] in ['critical', 'high']:
                    self.send_service_webhook_alert(alert, webhook_url)

        self.statistics["namespace_details"][namespace] = namespace_stats
        logger.info(f"Namespace {namespace}: {namespace_stats['services_count']} services, "
                   f"{namespace_stats['pods_count']} pods evaluated, "
                   f"availability score: {namespace_stats['service_availability_score']:.1f}%")
        return alerts

    def calculate_service_impact_severity(self, restart_info: Dict, log_analysis: Dict, service_availability: Dict) -> str:
        """Calculate severity based on service impact"""
        restart_count = restart_info["max_restarts"]
        log_severity = log_analysis.get("severity", "low")
        service_health = log_analysis.get("service_health_score", 100)
        
        # Check if this affects a critical service
        service_name = restart_info["service_name"]
        service_info = service_availability.get("services_detected", {}).get(service_name, {})
        service_availability_pct = service_info.get("availability_percentage", 100)
        
        # Base severity from restart count
        if restart_count > 50:
            base_severity = "critical"
        elif restart_count > 20:
            base_severity = "high"
        elif restart_count > 5:
            base_severity = "medium"
        else:
            base_severity = "low"
        
        # Upgrade severity based on service impact
        severity_levels = ["low", "medium", "high", "critical"]
        max_severity = severity_levels.index(base_severity)
        
        # Service health impact
        if service_health < 50:
            max_severity = min(len(severity_levels) - 1, max_severity + 1)
        elif service_health < 80:
            max_severity = min(len(severity_levels) - 1, max_severity + 0.5)
        
        # Service availability impact
        if service_availability_pct < 50:
            max_severity = min(len(severity_levels) - 1, max_severity + 1)
        elif service_availability_pct < 80:
            max_severity = min(len(severity_levels) - 1, max_severity + 0.5)
        
        # Log analysis impact
        log_severity_score = severity_levels.index(log_severity)
        max_severity = max(max_severity, log_severity_score)
        
        return severity_levels[int(max_severity)]

    def send_service_webhook_alert(self, alert: Dict, webhook_url: str):
        """Send service-focused webhook alert"""
        message_parts = [
            f"*Service Alert - {alert['severity'].upper()}*",
            f"Service: `{alert['service_name']}`",
            f"Namespace: `{alert['namespace']}`",
            f"Pod: `{alert['pod_name']}`",
            f"Restarts: `{alert['restart_count']}` (was {alert['previous_restart_count']})",
            f"Health Score: `{alert['service_health_score']}/100`",
            f"Status: `{alert['status']}`"
        ]
        
        # Add service recommendations
        recommendations = alert.get('recommendations', [])
        if recommendations:
            top_rec = recommendations[0]
            message_parts.extend([
                "",
                f"*Recommended Action ({top_rec['priority']}):*",
                f"```{top_rec['immediate_action']}```",
                f"{top_rec['title']}"
            ])
        
        message = "\n".join(message_parts)
        data = {"text": message}
        
        try:
            response = requests.post(webhook_url, json=data, timeout=10)
            logger.info(f"Sent service webhook alert for {alert['service_name']} in {alert['namespace']}")
        except Exception as e:
            logger.error(f"Failed to send service webhook alert: {e}")

    def monitor_all_namespaces(self) -> List[Dict[str, Any]]:
        """Monitor all managed namespaces"""
        if not self.check_cluster_connectivity():
            return []
        all_alerts = []
        for namespace in self.namespaces:
            namespace_alerts = self.check_namespace_services(namespace)
            all_alerts.extend(namespace_alerts)
        self.alerts = all_alerts
        self.save_current_state()
        return all_alerts

    def format_age(self, creation_time_str: str) -> str:
        """Format pod age in human-readable format"""
        try:
            if creation_time_str == "Unknown":
                return "Unknown"
            creation_time = datetime.datetime.fromisoformat(creation_time_str.replace('Z', '+00:00'))
            age = datetime.datetime.now(datetime.timezone.utc) - creation_time
            days = age.days
            hours, remainder = divmod(age.seconds, 3600)
            minutes, _ = divmod(remainder, 60)
            
            if days > 0:
                return f"{days}d{hours}h"
            elif hours > 0:
                return f"{hours}h{minutes}m"
            else:
                return f"{minutes}m"
        except:
            return "Unknown"

    def truncate_text(self, text: str, max_length: int = 30) -> str:
        """Truncate text to fit in table columns"""
        if len(text) <= max_length:
            return text
        return text[:max_length-3] + "..."

    def print_service_executive_summary(self):
        """Print executive summary focused on service health"""
        total_services = self.statistics['total_services_evaluated']
        total_alerts = len(self.alerts)
        critical_services = self.statistics['services_critical']
        degraded_services = self.statistics['services_degraded']
        
        if total_alerts == 0 and critical_services == 0:
            status = "[HEALTHY]"
            message = f"All {total_services} services operational"
        elif critical_services > 0:
            status = "[CRITICAL]" 
            message = f"{critical_services} services require immediate attention"
        elif degraded_services > 0:
            status = "[DEGRADED]"
            message = f"{degraded_services} services experiencing issues"
        else:
            status = "[WARNING]"
            message = f"{total_alerts} pod issues detected"
        
        print(f"\nSERVICE STATUS {status}: {message}")
        print(f"Monitoring Coverage: {total_services} services across {self.statistics['accessible_namespaces']} namespaces")
        print("="*80)

    def print_service_statistics(self):
        """Print service-focused statistics"""
        terminal_width = 80
        print("\n" + "="*terminal_width)
        print("SERVICE MONITORING SUMMARY")
        print("="*terminal_width)
        
        # Service health overview
        total_services = self.statistics['total_services_evaluated']
        healthy_services = self.statistics['services_healthy']
        degraded_services = self.statistics['services_degraded']
        critical_services = self.statistics['services_critical']
        
        scan_duration = f"{self.statistics.get('scan_duration_seconds', 0):.1f}s"
        namespaces = f"{self.statistics['accessible_namespaces']}/{self.statistics['total_namespaces_checked']}"
        
        print(f"Service Health: {healthy_services} Healthy | {degraded_services} Degraded | {critical_services} Critical")
        print(f"Scan Duration: {scan_duration} | Namespaces: {namespaces} | Pods Evaluated: {self.statistics['total_pods_evaluated']}")
        print(f"Restart Activity: {self.statistics['pods_with_restarts']} pods with restarts | {self.statistics['pods_above_threshold']} alerts generated")
        
        # Service alerts summary
        total_alerts = len(self.alerts)
        new_alerts = self.statistics['new_service_issues']
        repeat_alerts = self.statistics['repeated_service_issues']
        
        print(f"\nAlert Summary: {total_alerts} total alerts | {new_alerts} new issues | {repeat_alerts} recurring issues")
        
        # Namespace breakdown with service focus
        if self.statistics['namespace_details']:
            print(f"\nNAMESPACE SERVICE STATUS:")
            print("-" * terminal_width)
            
            namespace_data = []
            for ns, stats in self.statistics['namespace_details'].items():
                if stats['accessible']:
                    # Service health indicator
                    if stats['services_critical'] > 0:
                        status = "CRITICAL"
                    elif stats['services_degraded'] > 0:
                        status = "DEGRADED"
                    else:
                        status = "HEALTHY"
                    
                    # Service summary - FIXED LOGIC
                    total_services_in_ns = stats['services_critical'] + stats['services_degraded'] + stats['services_healthy']
                    service_summary = f"{total_services_in_ns} services"
                    
                    if stats['services_critical'] > 0 or stats['services_degraded'] > 0:
                        service_summary += f" ({stats['services_healthy']} healthy"
                        if stats['services_degraded'] > 0:
                            service_summary += f", {stats['services_degraded']} degraded"
                        if stats['services_critical'] > 0:
                            service_summary += f", {stats['services_critical']} critical"
                        service_summary += ")"
                    
                    availability = f"{stats['service_availability_score']:.1f}%"
                    pod_info = f"{stats['pods_count']} pods, {stats['pods_above_threshold']} alerts"
                    
                    namespace_data.append([
                        status,
                        self.truncate_text(ns, 20),
                        service_summary,
                        availability,
                        pod_info
                    ])
                else:
                    namespace_data.append([
                        "INACCESSIBLE",
                        self.truncate_text(ns, 20),
                        "Unable to connect",
                        "-",
                        "-"
                    ])
            
            headers = ["Status", "Namespace", "Services", "Availability", "Pod Info"]
            print(tabulate(namespace_data, headers=headers, tablefmt="grid"))

    def print_service_alerts_table(self):
        """Print service-focused alerts table"""
        if not self.alerts:
            print(f"\nSTATUS: All services healthy - no restart issues above threshold ({self.restart_threshold})")
            print("="*80)
            return
            
        terminal_width = 80
        print(f"\nSERVICE ISSUES DETECTED ({len(self.alerts)} problems requiring attention)")
        print("="*terminal_width)
        
        # Sort by service impact (critical services first)
        sorted_alerts = sorted(self.alerts, 
                             key=lambda x: (
                                 {"critical": 0, "high": 1, "medium": 2, "low": 3}[x['severity']],
                                 -x['service_health_score'],
                                 -x['restart_count']
                             ))
        
        # Service-focused alert display
        alert_data = []
        for i, alert in enumerate(sorted_alerts, 1):
            severity = alert['severity'].upper()
            issue_type = "NEW" if alert['is_new_issue'] else "RECURRING"
            
            # Service and pod info
            service_name = self.truncate_text(alert['service_name'], 18)
            pod_name = self.truncate_text(alert['pod_name'], 20)
            namespace = self.truncate_text(alert['namespace'], 15)
            age = self.format_age(alert['creation_time'])
            
            # Restart and health info
            restart_info = f"{alert['restart_count']}"
            if alert['previous_restart_count'] > 0:
                change = alert['restart_count'] - alert['previous_restart_count']
                restart_info += f" (+{change})"
            
            health_score = alert.get('service_health_score', 100)
            
            # Container health
            containers = alert['containers']
            ready_count = sum(1 for c in containers if c.get('ready', False))
            total_count = len(containers)
            container_status = f"{ready_count}/{total_count}"
            
            # Service issue category
            issues = alert.get('log_analysis', {}).get('service_issues', [])
            issue_category = issues[0]['category'] if issues else 'GENERAL'
            
            alert_data.append([
                i,
                severity,
                issue_type,
                namespace,
                service_name,
                pod_name,
                restart_info,
                f"{health_score}/100",
                container_status,
                issue_category,
                age
            ])
        
        headers = ["#", "Severity", "Type", "Namespace", "Service", "Pod", "Restarts", "Health", "Ready", "Category", "Age"]
        print(tabulate(alert_data, headers=headers, tablefmt="grid"))
        
        # Show actionable recommendations for service issues
        critical_alerts = [a for a in sorted_alerts if a['severity'] in ['critical', 'high'] and a.get('recommendations')]
        if critical_alerts:
            print(f"\nRECOMMENDED ACTIONS:")
            print("-" * terminal_width)
            
            for i, alert in enumerate(critical_alerts[:5], 1):
                service_ref = f"{alert['namespace']}/{alert['service_name']}"
                recommendations = alert['recommendations']
                
                if recommendations:
                    top_rec = recommendations[0]
                    priority = top_rec['priority']
                    
                    print(f"\n{i}. [{priority}] {service_ref}")
                    print(f"   Issue: {top_rec['title']}")
                    print(f"   Immediate Action: {self.truncate_text(top_rec['immediate_action'], 70)}")
                    
                    # Show follow-up if available
                    if 'follow_up' in top_rec:
                        print(f"   Follow-up Command: {self.truncate_text(top_rec['follow_up'], 65)}")

        # Show service health insights
        self.print_service_insights()

    def print_service_insights(self):
        """Print service-specific insights"""
        if not self.alerts:
            return
            
        print(f"\nSERVICE HEALTH ANALYSIS:")
        print("-" * 80)
        
        # Service issue analysis
        service_issues = {}
        for alert in self.alerts:
            service_name = alert['service_name']
            if service_name not in service_issues:
                service_issues[service_name] = []
            service_issues[service_name].append(alert)
        
        # Show most problematic services
        problematic_services = sorted(service_issues.items(), 
                                    key=lambda x: len(x[1]), reverse=True)[:3]
        
        if problematic_services:
            service_summary = " | ".join([f"{svc}: {len(alerts)} issues" 
                                        for svc, alerts in problematic_services])
            print(f"Most Affected Services: {service_summary}")
        
        # Common issue categories for services
        all_issues = []
        for alert in self.alerts:
            issues = alert.get('log_analysis', {}).get('service_issues', [])
            all_issues.extend([issue['category'] for issue in issues])
        
        if all_issues:
            from collections import Counter
            common_issues = Counter(all_issues).most_common(3)
            issues_text = ", ".join([f"{issue} ({count})" for issue, count in common_issues])
            print(f"Common Issue Categories: {issues_text}")
        
        # Service availability summary
        total_availability = 0
        namespace_count = 0
        for namespace, availability_data in self.statistics.get("service_availability", {}).items():
            if availability_data.get("availability_score") is not None:
                total_availability += availability_data["availability_score"]
                namespace_count += 1
        
        if namespace_count > 0:
            avg_availability = total_availability / namespace_count
            if avg_availability < 95:
                print(f"WARNING: Overall service availability at {avg_availability:.1f}% (target: 95%)")

    def save_service_alerts_to_csv(self, filename: str = None):
        """Save service alerts to CSV"""
        if filename is None:
            filename = os.path.join(self.output_dir, 'service_alerts.csv')
        if not self.alerts:
            logger.info("No service alerts to save")
            return
        with open(filename, 'w', newline='') as csvfile:
            fieldnames = ['timestamp', 'namespace', 'service_name', 'pod_name', 'restart_count',
                         'previous_restart_count', 'is_new_issue', 'severity', 'service_health_score',
                         'status', 'node', 'creation_time']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            for alert in self.alerts:
                writer.writerow({
                    'timestamp': alert['timestamp'],
                    'namespace': alert['namespace'],
                    'service_name': alert['service_name'],
                    'pod_name': alert['pod_name'],
                    'restart_count': alert['restart_count'],
                    'previous_restart_count': alert['previous_restart_count'],
                    'is_new_issue': alert['is_new_issue'],
                    'severity': alert['severity'],
                    'service_health_score': alert.get('service_health_score', 100),
                    'status': alert['status'],
                    'node': alert['node'],
                    'creation_time': alert['creation_time']
                })
        logger.info(f"Service alerts saved to {filename}")

    def save_service_detailed_report(self, filename: str = None):
        """Save detailed service report"""
        if filename is None:
            filename = os.path.join(self.output_dir, 'service_detailed_report.json')
        
        service_report = {
            "scan_info": {
                "timestamp": datetime.datetime.now().isoformat(),
                "duration_seconds": self.statistics.get('scan_duration_seconds', 0),
                "monitoring_focus": "namespace_services"
            },
            "service_summary": {
                "total_services": self.statistics['total_services_evaluated'],
                "healthy_services": self.statistics['services_healthy'],
                "degraded_services": self.statistics['services_degraded'],
                "critical_services": self.statistics['services_critical'],
                "total_alerts": len(self.alerts)
            },
            "namespace_service_health": self.statistics.get("service_availability", {}),
            "service_alerts": self.alerts,
            "recommendations_summary": [
                {
                    "service": alert['service_name'],
                    "namespace": alert['namespace'],
                    "priority": alert['recommendations'][0]['priority'] if alert['recommendations'] else 'N/A',
                    "action": alert['recommendations'][0]['immediate_action'] if alert['recommendations'] else 'N/A'
                }
                for alert in self.alerts if alert.get('recommendations')
            ]
        }
        
        try:
            with open(filename, 'w') as f:
                json.dump(service_report, f, indent=2)
            logger.info(f"Service detailed report saved to {filename}")
        except Exception as e:
            logger.error(f"Failed to save service report: {e}")

    def generate_service_action_plan(self) -> List[Dict[str, str]]:
        """Generate prioritized action plan for service issues"""
        action_plan = []
        
        # Focus on critical and high severity service issues
        critical_alerts = [a for a in self.alerts if a['severity'] == 'critical']
        high_alerts = [a for a in self.alerts if a['severity'] == 'high']
        
        # Critical service issues first
        for alert in critical_alerts[:3]:
            recommendations = alert.get('recommendations', [])
            if recommendations:
                action_plan.append({
                    'priority': 'CRITICAL SERVICE',
                    'service': alert['service_name'],
                    'namespace': alert['namespace'],
                    'action': recommendations[0]['immediate_action'],
                    'reason': f"Service health: {alert.get('service_health_score', 0)}/100"
                })
        
        # High priority service issues
        for alert in high_alerts[:2]:
            recommendations = alert.get('recommendations', [])
            if recommendations:
                action_plan.append({
                    'priority': 'HIGH SERVICE',
                    'service': alert['service_name'],
                    'namespace': alert['namespace'],
                    'action': recommendations[0]['immediate_action'],
                    'reason': f"Restart count: {alert['restart_count']}"
                })
        
        # Namespace-wide service issues
        for namespace, stats in self.statistics['namespace_details'].items():
            if stats.get('service_availability_score', 100) < 80:
                action_plan.append({
                    'priority': 'NAMESPACE',
                    'service': 'all-services',
                    'namespace': namespace,
                    'action': f'kubectl get pods -n {namespace} -o wide',
                    'reason': f"Namespace availability: {stats['service_availability_score']:.1f}%"
                })
        
        return action_plan

    def print_statistics(self):
        """Main statistics display focused on services"""
        self.print_service_executive_summary()
        self.print_service_statistics()

    def print_alerts_summary(self):
        """Main alerts display focused on services"""
        self.print_service_alerts_table()


def main():
    parser = argparse.ArgumentParser(description='Professional Service Monitoring for Kubernetes Namespaces')
    parser.add_argument('--namespaces', nargs='+',
                       help='List of namespaces to monitor (services you own)')
    parser.add_argument('--threshold', type=int, default=1,
                       help='Restart count threshold for alerts (default: 1)')
    parser.add_argument('--config', type=str,
                       help='Path to YAML configuration file')
    parser.add_argument('--output-csv',
                       help='Service alerts CSV output file path')
    parser.add_argument('--output-json',
                       help='Service report JSON output file path')
    parser.add_argument('--stats-json',
                       help='Statistics JSON output file path')
    parser.add_argument('--quiet', action='store_true',
                       help='Only show service statistics, suppress detailed alerts')
    parser.add_argument('--watch', action='store_true',
                       help='Continuously monitor services')
    parser.add_argument('--watch-interval', type=int, default=300,
                       help='Watch mode interval in seconds (default: 300)')
    parser.add_argument('--label-selector', type=str,
                       help='Kubectl label selector for service pods')
    parser.add_argument('--generate-actions', action='store_true',
                       help='Generate actionable service recovery steps')
    args = parser.parse_args()

    config = {}
    if args.config:
        try:
            with open(args.config, 'r') as f:
                config = yaml.safe_load(f)
        except Exception as e:
            logger.error(f"Failed to load config file {args.config}: {e}")
            sys.exit(1)
    
    namespaces = args.namespaces
    if not namespaces and config.get('namespaces'):
        namespaces = config['namespaces']
    if not namespaces:
        parser.error("No namespaces specified. Use --namespaces or provide config file with namespaces.")
    
    threshold = args.threshold
    if config.get('monitoring', {}).get('restart_threshold'):
        threshold = config['monitoring']['restart_threshold']
    
    def run_service_monitoring():
        monitor = NamespaceServiceMonitor(namespaces, threshold, config, args.label_selector)
        logger.info("Starting professional service monitoring for your namespaces...")
        
        alerts = monitor.monitor_all_namespaces()
        
        # Save service-focused outputs
        monitor.save_service_alerts_to_csv(args.output_csv)
        monitor.save_service_detailed_report(args.output_json)
        
        # Calculate final statistics
        monitor.statistics["scan_end_time"] = datetime.datetime.now().isoformat()
        scan_start = datetime.datetime.fromisoformat(monitor.statistics["scan_start_time"])
        scan_end = datetime.datetime.fromisoformat(monitor.statistics["scan_end_time"])
        monitor.statistics["scan_duration_seconds"] = (scan_end - scan_start).total_seconds()
        
        # Save statistics
        if args.stats_json:
            with open(args.stats_json, 'w') as f:
                json.dump(monitor.statistics, f, indent=2)
        
        # Display service-focused results
        monitor.print_statistics()
        if not args.quiet:
            monitor.print_alerts_summary()
        
        # Generate service action plan if requested
        if args.generate_actions and alerts:
            action_plan = monitor.generate_service_action_plan()
            if action_plan:
                print(f"\nSERVICE RECOVERY PLAN:")
                print("="*80)
                for i, action in enumerate(action_plan, 1):
                    print(f"{i}. [{action['priority']}] {action['namespace']}/{action['service']}")
                    print(f"   Command: {action['action']}")
                    print(f"   Reason: {action['reason']}\n")
        
        # Service-focused summary
        total_services = monitor.statistics['total_services_evaluated']
        critical_services = monitor.statistics['services_critical']
        degraded_services = monitor.statistics['services_degraded']
        
        logger.info(f"Service monitoring complete. Monitored {total_services} services "
                   f"across {monitor.statistics['accessible_namespaces']} namespaces. "
                   f"Status: {monitor.statistics['services_healthy']} healthy, "
                   f"{degraded_services} degraded, {critical_services} critical. "
                   f"Found {len(alerts)} pod issues requiring attention.")
        
        return critical_services, len(alerts)
    
    if args.watch:
        logger.info(f"Starting continuous service monitoring - checking every {args.watch_interval} seconds")
        try:
            while True:
                critical_services, alert_count = run_service_monitoring()
                print(f"\nNext check in {args.watch_interval} seconds... (Ctrl+C to stop)")
                time.sleep(args.watch_interval)
        except KeyboardInterrupt:
            logger.info("Service monitoring stopped by user")
            sys.exit(0)
    else:
        critical_services, alert_count = run_service_monitoring()
        
        # Exit codes based on service health
        # 0: All services healthy
        # 1: Some services degraded or pod issues
        # 2: Critical services down
        if critical_services > 0:
            sys.exit(2)  # Critical services need immediate attention
        elif alert_count > 0:
            sys.exit(1)  # Some issues detected
        else:
            sys.exit(0)  # All services healthy

if __name__ == "__main__":
    main()
