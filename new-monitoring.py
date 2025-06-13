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

# For CI environments, prefer current directory over temp directory
def get_output_directory():
    """Get appropriate output directory for CI/local environments"""
    if os.environ.get('CI'):  # GitLab CI sets this variable
        # In CI, use current directory for artifacts
        output_dir = os.path.join(os.getcwd(), 'monitoring-output')
        os.makedirs(output_dir, exist_ok=True)
        return output_dir
    else:
        # Local development, use temp directory
        return tempfile.gettempdir()

# Set up output directory
OUTPUT_DIR = get_output_directory()
log_file_path = os.path.join(OUTPUT_DIR, 'pod_restart_monitor.log')

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file_path),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Log the output directory being used
logger.info(f"Output directory: {OUTPUT_DIR}")
if os.environ.get('CI'):
    logger.info("Running in CI environment - artifacts will be saved to monitoring-output/")

class KubernetesPodMonitor:
    def __init__(self, namespaces: List[str], restart_threshold: int = 1, config: Dict[str, Any] = None):
        self.namespaces = namespaces
        self.restart_threshold = restart_threshold
        self.config = config or {}
        self.alerts = []
        self.previous_state = {}
        
        # Use the global output directory
        self.output_dir = OUTPUT_DIR
        
        self.statistics = {
            "scan_start_time": datetime.datetime.now().isoformat(),
            "total_namespaces_checked": 0,
            "accessible_namespaces": 0,
            "inaccessible_namespaces": 0,
            "total_pods_evaluated": 0,
            "total_containers_evaluated": 0,
            "total_services_found": 0,
            "total_deployments_found": 0,
            "pods_with_restarts": 0,
            "pods_above_threshold": 0,
            "new_alerts": 0,
            "repeated_alerts": 0,
            "cluster_info": {},
            "namespace_details": {},
            "environment": {
                "ci": os.environ.get('CI', False),
                "gitlab_ci": os.environ.get('GITLAB_CI', False),
                "job_name": os.environ.get('CI_JOB_NAME', 'local'),
                "pipeline_id": os.environ.get('CI_PIPELINE_ID', 'local'),
                "output_directory": self.output_dir
            }
        }
        
        # Load previous state for tracking changes
        self.load_previous_state()
        
        # Get cluster information
        self.get_cluster_info()
        
    def load_config_file(self, config_path: str) -> Dict[str, Any]:
        """Load configuration from YAML file"""
        try:
            with open(config_path, 'r') as f:
                return yaml.safe_load(f)
        except Exception as e:
            logger.error(f"Failed to load config file {config_path}: {e}")
            return {}
    
    def load_previous_state(self):
        """Load previous monitoring state for change detection"""
        state_file = self.config.get('state_file', os.path.join(self.output_dir, 'k8s_monitor_state.json'))
        try:
            if os.path.exists(state_file):
                with open(state_file, 'r') as f:
                    self.previous_state = json.load(f)
                logger.info(f"Loaded previous state from {state_file}")
        except Exception as e:
            logger.warning(f"Could not load previous state: {e}")
            self.previous_state = {}
    
    def save_current_state(self):
        """Save current monitoring state for next run"""
        state_file = self.config.get('state_file', os.path.join(self.output_dir, 'k8s_monitor_state.json'))
        current_state = {
            "last_run": datetime.datetime.now().isoformat(),
            "pod_restart_counts": {},
            "alerts": self.alerts,
            "environment": self.statistics["environment"]
        }
        
        # Save current restart counts for each pod
        for namespace in self.namespaces:
            pods = self.get_pods_in_namespace(namespace)
            for pod in pods:
                pod_key = f"{namespace}/{pod['metadata']['name']}"
                restart_info = self.extract_restart_info(pod)
                current_state["pod_restart_counts"][pod_key] = restart_info["max_restarts"]
        
        try:
            with open(state_file, 'w') as f:
                json.dump(current_state, f, indent=2)
            logger.info(f"Saved current state to {state_file}")
        except Exception as e:
            logger.error(f"Could not save state: {e}")
    
    def get_cluster_info(self):
        """Get cluster information for context"""
        try:
            # Get cluster info
            result = subprocess.run(
                ["kubectl", "cluster-info"], 
                capture_output=True, 
                text=True, 
                check=True
            )
            
            # Get current context
            context_result = subprocess.run(
                ["kubectl", "config", "current-context"], 
                capture_output=True, 
                text=True, 
                check=True
            )
            
            # Get server version
            version_result = subprocess.run(
                ["kubectl", "version", "--short"], 
                capture_output=True, 
                text=True
            )
            
            self.statistics["cluster_info"] = {
                "current_context": context_result.stdout.strip(),
                "version_info": version_result.stdout.strip() if version_result.returncode == 0 else "Unknown",
                "cluster_accessible": True
            }
            
        except Exception as e:
            logger.warning(f"Could not get cluster info: {e}")
            self.statistics["cluster_info"] = {"cluster_accessible": False, "error": str(e)}
        
    def run_kubectl_command(self, command: List[str]) -> Dict[str, Any]:
        """Execute kubectl command and return JSON output"""
        try:
            result = subprocess.run(
                command, 
                capture_output=True, 
                text=True, 
                check=True,
                timeout=30  # Add timeout
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
    
    def check_cluster_connectivity(self) -> bool:
        """Check if we can connect to the Kubernetes cluster"""
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
    
    def get_pods_in_namespace(self, namespace: str) -> List[Dict[str, Any]]:
        """Get all pods in a specific namespace"""
        command = ["kubectl", "get", "pods", "-n", namespace, "-o", "json"]
        result = self.run_kubectl_command(command)
        return result.get("items", [])
    
    def get_services_in_namespace(self, namespace: str) -> List[Dict[str, Any]]:
        """Get all services in a specific namespace"""
        command = ["kubectl", "get", "services", "-n", namespace, "-o", "json"]
        result = self.run_kubectl_command(command)
        return result.get("items", [])
    
    def get_deployments_in_namespace(self, namespace: str) -> List[Dict[str, Any]]:
        """Get all deployments in a specific namespace"""
        command = ["kubectl", "get", "deployments", "-n", namespace, "-o", "json"]
        result = self.run_kubectl_command(command)
        return result.get("items", [])
    
    def get_events_for_pod(self, namespace: str, pod_name: str) -> List[Dict[str, Any]]:
        """Get recent events for a specific pod"""
        command = ["kubectl", "get", "events", "-n", namespace, 
                  "--field-selector", f"involvedObject.name={pod_name}",
                  "-o", "json"]
        result = self.run_kubectl_command(command)
        return result.get("items", [])
    
    def is_pod_filtered(self, pod: Dict[str, Any]) -> bool:
        """Check if pod should be filtered out based on configuration"""
        if not self.config.get('filters'):
            return False
            
        filters = self.config['filters']
        pod_name = pod["metadata"]["name"]
        
        # Check exclude patterns
        exclude_patterns = filters.get('exclude_pods_pattern', [])
        for pattern in exclude_patterns:
            if re.match(pattern, pod_name):
                logger.debug(f"Pod {pod_name} excluded by pattern {pattern}")
                return True
        
        # Check pod age filter
        max_age_hours = filters.get('max_pod_age_hours')
        if max_age_hours:
            creation_time = datetime.datetime.fromisoformat(
                pod["metadata"]["creationTimestamp"].replace('Z', '+00:00')
            )
            age = datetime.datetime.now(datetime.timezone.utc) - creation_time
            if age.total_seconds() < max_age_hours * 3600:
                logger.debug(f"Pod {pod_name} too young, skipping")
                return True
        
        # Check if only running pods should be included
        if filters.get('include_only_running'):
            if pod["status"].get("phase") != "Running":
                return True
                
        return False
    
    def extract_restart_info(self, pod: Dict[str, Any]) -> Dict[str, Any]:
        """Extract restart information from pod data"""
        pod_name = pod["metadata"]["name"]
        namespace = pod["metadata"]["namespace"]
        
        restart_info = {
            "pod_name": pod_name,
            "namespace": namespace,
            "node": pod["spec"].get("nodeName", "Unknown"),
            "phase": pod["status"].get("phase", "Unknown"),
            "creation_time": pod["metadata"].get("creationTimestamp", "Unknown"),
            "containers": []
        }
        
        # Check container statuses
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
            
            # Get last termination reason if available
            last_state = container.get("lastState", {})
            if "terminated" in last_state:
                container_info["last_termination_reason"] = last_state["terminated"].get("reason", "Unknown")
                container_info["last_termination_time"] = last_state["terminated"].get("finishedAt", "Unknown")
                container_info["exit_code"] = last_state["terminated"].get("exitCode", "Unknown")
            
            restart_info["containers"].append(container_info)
        
        restart_info["max_restarts"] = max_restarts
        
        # Check if this is a new alert or repeated
        pod_key = f"{namespace}/{pod_name}"
        previous_restarts = self.previous_state.get("pod_restart_counts", {}).get(pod_key, 0)
        restart_info["is_new_issue"] = restart_info["max_restarts"] > previous_restarts
        restart_info["previous_restart_count"] = previous_restarts
        
        return restart_info
    
    def get_pod_logs_tail(self, namespace: str, pod_name: str, lines: int = 10) -> str:
        """Get last few lines of pod logs"""
        try:
            command = ["kubectl", "logs", pod_name, "-n", namespace, "--tail", str(lines)]
            result = subprocess.run(command, capture_output=True, text=True, timeout=10)
            return result.stdout if result.returncode == 0 else "Could not retrieve logs"
        except Exception as e:
            return f"Error getting logs: {e}"
    
    def check_namespace_for_restarts(self, namespace: str) -> List[Dict[str, Any]]:
        """Check a namespace for pods with high restart counts"""
        logger.info(f"Checking namespace: {namespace}")
        alerts = []
        
        # Initialize namespace statistics
        namespace_stats = {
            "accessible": False,
            "pods_count": 0,
            "containers_count": 0,
            "services_count": 0,
            "deployments_count": 0,
            "pods_with_restarts": 0,
            "pods_above_threshold": 0,
            "filtered_pods": 0
        }
        
        self.statistics["total_namespaces_checked"] += 1
        
        # Check if namespace exists
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
        
        # Get resources in namespace
        pods = self.get_pods_in_namespace(namespace)
        services = self.get_services_in_namespace(namespace)
        deployments = self.get_deployments_in_namespace(namespace)
        
        # Update statistics
        namespace_stats["pods_count"] = len(pods)
        namespace_stats["services_count"] = len(services)
        namespace_stats["deployments_count"] = len(deployments)
        
        self.statistics["total_pods_evaluated"] += len(pods)
        self.statistics["total_services_found"] += len(services)
        self.statistics["total_deployments_found"] += len(deployments)
        
        # Process each pod
        for pod in pods:
            # Check if pod should be filtered
            if self.is_pod_filtered(pod):
                namespace_stats["filtered_pods"] += 1
                continue
                
            restart_info = self.extract_restart_info(pod)
            
            # Count containers
            container_count = len(restart_info["containers"])
            namespace_stats["containers_count"] += container_count
            self.statistics["total_containers_evaluated"] += container_count
            
            # Check for restarts
            if restart_info["max_restarts"] > 0:
                namespace_stats["pods_with_restarts"] += 1
                self.statistics["pods_with_restarts"] += 1
            
            if restart_info["max_restarts"] > self.restart_threshold:
                namespace_stats["pods_above_threshold"] += 1
                self.statistics["pods_above_threshold"] += 1
                
                # Get additional information for alerts
                events = self.get_events_for_pod(namespace, restart_info["pod_name"])
                recent_logs = self.get_pod_logs_tail(namespace, restart_info["pod_name"])
                
                alert = {
                    "timestamp": datetime.datetime.now().isoformat(),
                    "namespace": namespace,
                    "pod_name": restart_info["pod_name"],
                    "restart_count": restart_info["max_restarts"],
                    "previous_restart_count": restart_info["previous_restart_count"],
                    "is_new_issue": restart_info["is_new_issue"],
                    "status": restart_info["phase"],
                    "node": restart_info["node"],
                    "creation_time": restart_info["creation_time"],
                    "containers": restart_info["containers"],
                    "recent_events": events[-3:] if events else [],  # Last 3 events
                    "recent_logs": recent_logs,
                    "severity": self.calculate_alert_severity(restart_info)
                }
                alerts.append(alert)
                
                # Track new vs repeated alerts
                if restart_info["is_new_issue"]:
                    self.statistics["new_alerts"] += 1
                else:
                    self.statistics["repeated_alerts"] += 1
                
                severity_emoji = {"high": "🔥", "medium": "⚠️", "low": "ℹ️"}
                logger.warning(
                    f"{severity_emoji[alert['severity']]} ALERT: Pod {restart_info['pod_name']} in namespace {namespace} "
                    f"has {restart_info['max_restarts']} restarts (was {restart_info['previous_restart_count']})"
                )
        
        self.statistics["namespace_details"][namespace] = namespace_stats
        logger.info(f"Namespace {namespace}: {namespace_stats['pods_count']} pods, "
                   f"{namespace_stats['services_count']} services, "
                   f"{namespace_stats['deployments_count']} deployments evaluated "
                   f"({namespace_stats['filtered_pods']} filtered)")
        
        return alerts
    
    def calculate_alert_severity(self, restart_info: Dict[str, Any]) -> str:
        """Calculate severity based on restart count and frequency"""
        restart_count = restart_info["max_restarts"]
        
        if restart_count > 10:
            return "high"
        elif restart_count > 5:
            return "medium"
        else:
            return "low"
    
    def monitor_all_namespaces(self) -> List[Dict[str, Any]]:
        """Monitor all specified namespaces for restart issues"""
        if not self.check_cluster_connectivity():
            return []
        
        all_alerts = []
        
        for namespace in self.namespaces:
            namespace_alerts = self.check_namespace_for_restarts(namespace)
            all_alerts.extend(namespace_alerts)
        
        self.alerts = all_alerts
        
        # Save current state for next run
        self.save_current_state()
        
        return all_alerts
    
    def save_alerts_to_csv(self, filename: str = None):
        """Save alerts to CSV file"""
        if filename is None:
            filename = os.path.join(self.output_dir, 'restart_alerts.csv')
            
        if not self.alerts:
            logger.info("No alerts to save")
            return
        
        with open(filename, 'w', newline='') as csvfile:
            fieldnames = ['timestamp', 'namespace', 'pod_name', 'restart_count', 
                         'previous_restart_count', 'is_new_issue', 'severity', 
                         'status', 'node', 'creation_time']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            
            writer.writeheader()
            for alert in self.alerts:
                writer.writerow({
                    'timestamp': alert['timestamp'],
                    'namespace': alert['namespace'],
                    'pod_name': alert['pod_name'],
                    'restart_count': alert['restart_count'],
                    'previous_restart_count': alert['previous_restart_count'],
                    'is_new_issue': alert['is_new_issue'],
                    'severity': alert['severity'],
                    'status': alert['status'],
                    'node': alert['node'],
                    'creation_time': alert['creation_time']
                })
        
        logger.info(f"Alerts saved to {filename}")
    
    def save_detailed_alerts_to_json(self, filename: str = None):
        """Save detailed alerts to JSON file"""
        if filename is None:
            filename = os.path.join(self.output_dir, 'restart_alerts_detailed.json')
            
        if not self.alerts:
            logger.info("No detailed alerts to save")
            return
        
        with open(filename, 'w') as jsonfile:
            json.dump(self.alerts, jsonfile, indent=2)
        
        logger.info(f"Detailed alerts saved to {filename}")
    
    def save_statistics_to_json(self, filename: str = None):
        """Save monitoring statistics to JSON file"""
        if filename is None:
            filename = os.path.join(self.output_dir, 'monitoring_statistics.json')
            
        # Add scan completion time
        self.statistics["scan_end_time"] = datetime.datetime.now().isoformat()
        scan_start = datetime.datetime.fromisoformat(self.statistics["scan_start_time"])
        scan_end = datetime.datetime.fromisoformat(self.statistics["scan_end_time"])
        self.statistics["scan_duration_seconds"] = (scan_end - scan_start).total_seconds()
        
        with open(filename, 'w') as jsonfile:
            json.dump(self.statistics, jsonfile, indent=2)
        logger.info(f"Statistics saved to {filename}")
    
    def print_statistics(self):
        """Print detailed monitoring statistics"""
        print("\n" + "="*70)
        print("🔍 KUBERNETES MONITORING STATISTICS")
        print("="*70)
        
        # Environment info
        env = self.statistics.get("environment", {})
        if env.get("ci"):
            print(f"🤖 CI ENVIRONMENT:")
            print(f"   • Job: {env.get('job_name', 'Unknown')}")
            print(f"   • Pipeline: {env.get('pipeline_id', 'Unknown')}")
            print(f"   • Output directory: {env.get('output_directory', 'Unknown')}")
        
        # Cluster info
        cluster_info = self.statistics.get("cluster_info", {})
        if cluster_info.get("cluster_accessible"):
            print(f"🌐 CLUSTER INFO:")
            print(f"   • Context: {cluster_info.get('current_context', 'Unknown')}")
            print(f"   • Version: {cluster_info.get('version_info', 'Unknown')}")
        
        print(f"\n📊 SCAN SUMMARY:")
        print(f"   • Scan started: {self.statistics['scan_start_time']}")
        if 'scan_duration_seconds' in self.statistics:
            print(f"   • Duration: {self.statistics['scan_duration_seconds']:.2f} seconds")
        print(f"   • Total namespaces requested: {len(self.namespaces)}")
        print(f"   • Namespaces checked: {self.statistics['total_namespaces_checked']}")
        print(f"   • Accessible namespaces: {self.statistics['accessible_namespaces']}")
        print(f"   • Inaccessible namespaces: {self.statistics['inaccessible_namespaces']}")
        
        print(f"\n🔍 RESOURCES EVALUATED:")
        print(f"   • Total pods evaluated: {self.statistics['total_pods_evaluated']}")
        print(f"   • Total containers evaluated: {self.statistics['total_containers_evaluated']}")
        print(f"   • Total services found: {self.statistics['total_services_found']}")
        print(f"   • Total deployments found: {self.statistics['total_deployments_found']}")
        
        print(f"\n🚨 RESTART ANALYSIS:")
        print(f"   • Pods with any restarts: {self.statistics['pods_with_restarts']}")
        print(f"   • Pods above threshold ({self.restart_threshold}): {self.statistics['pods_above_threshold']}")
        print(f"   • New alerts: {self.statistics['new_alerts']}")
        print(f"   • Repeated alerts: {self.statistics['repeated_alerts']}")
        print(f"   • Alert threshold: > {self.restart_threshold} restarts")
        
        if self.statistics['total_pods_evaluated'] > 0:
            restart_percentage = (self.statistics['pods_with_restarts'] / self.statistics['total_pods_evaluated']) * 100
            alert_percentage = (self.statistics['pods_above_threshold'] / self.statistics['total_pods_evaluated']) * 100
            print(f"   • Pods with restarts: {restart_percentage:.1f}%")
            print(f"   • Pods triggering alerts: {alert_percentage:.1f}%")
        
        print(f"\n📋 NAMESPACE BREAKDOWN:")
        for namespace, stats in self.statistics['namespace_details'].items():
            status = "✅ Accessible" if stats['accessible'] else "❌ Inaccessible"
            if stats['accessible']:
                print(f"   {namespace}: {status}")
                print(f"      ├─ Pods: {stats['pods_count']} ({stats['containers_count']} containers)")
                print(f"      ├─ Services: {stats['services_count']}")
                print(f"      ├─ Deployments: {stats['deployments_count']}")
                print(f"      ├─ Filtered pods: {stats['filtered_pods']}")
                print(f"      ├─ Pods with restarts: {stats['pods_with_restarts']}")
                print(f"      └─ Pods above threshold: {stats['pods_above_threshold']}")
            else:
                print(f"   {namespace}: {status}")
        
        print("="*70)

    def print_alerts_summary(self):
        """Print a summary of the alerts found"""
        if self.alerts:
            print(f"\n🚨 RESTART ALERTS DETAILS ({len(self.alerts)} alerts)")
            print("="*70)
            
            # Group alerts by severity
            severity_groups = {"high": [], "medium": [], "low": []}
            for alert in self.alerts:
                severity_groups[alert["severity"]].append(alert)
            
            for severity in ["high", "medium", "low"]:
                if severity_groups[severity]:
                    severity_emoji = {"high": "🔥", "medium": "⚠️", "low": "ℹ️"}
                    print(f"\n{severity_emoji[severity]} {severity.upper()} SEVERITY ALERTS ({len(severity_groups[severity])})")
                    print("-" * 50)
                    
                    for alert in severity_groups[severity]:
                        new_badge = "🆕 NEW" if alert['is_new_issue'] else "🔄 REPEAT"
                        print(f"{new_badge} - {alert['namespace']}/{alert['pod_name']}")
                        print(f"   Restarts: {alert['restart_count']} (was {alert['previous_restart_count']})")
                        print(f"   Status: {alert['status']} | Node: {alert['node']}")
                        print(f"   Created: {alert['creation_time']}")
                        
                        # Container details
                        print("   Containers:")
                        for container in alert['containers']:
                            state_emoji = "✅" if container['ready'] else "❌"
                            print(f"      {state_emoji} {container['name']}: {container['restart_count']} restarts ({container['state']})")
                            if 'last_termination_reason' in container:
                                print(f"         Last exit: {container['last_termination_reason']} (code: {container.get('exit_code', 'N/A')})")
                        
                        # Show recent logs if available
                        if alert.get('recent_logs') and alert['recent_logs'] != "Could not retrieve logs":
                            print(f"   Recent logs preview:")
                            log_lines = alert['recent_logs'].split('\n')[:3]  # First 3 lines
                            for line in log_lines:
                                if line.strip():
                                    print(f"      {line[:80]}...")
                        
                        print()
            
        else:
            print(f"\n✅ No pods found with restart count > {self.restart_threshold}")
            print("="*70)

def main():
    parser = argparse.ArgumentParser(description='Enhanced Kubernetes pod restart monitor')
    parser.add_argument('--namespaces', nargs='+', 
                       help='List of namespaces to monitor')
    parser.add_argument('--threshold', type=int, default=1,
                       help='Restart count threshold (default: 1)')
    parser.add_argument('--config', type=str,
                       help='Path to YAML configuration file')
    parser.add_argument('--output-csv', 
                       help='CSV output file path (default: monitoring-output directory)')
    parser.add_argument('--output-json', 
                       help='JSON output file path (default: monitoring-output directory)')
    parser.add_argument('--stats-json', 
                       help='Statistics JSON output file path (default: monitoring-output directory)')
    parser.add_argument('--quiet', action='store_true',
                       help='Only show statistics, suppress detailed alerts')
    parser.add_argument('--watch', action='store_true',
                       help='Run continuously, monitoring every few minutes')
    parser.add_argument('--watch-interval', type=int, default=300,
                       help='Watch mode interval in seconds (default: 300)')
    
    args = parser.parse_args()
    
    # Load configuration
    config = {}
    if args.config:
        config = yaml.safe_load(open(args.config, 'r'))
    
    # Determine namespaces
    namespaces = args.namespaces
    if not namespaces and config.get('namespaces'):
        namespaces = config['namespaces']
    if not namespaces:
        parser.error("No namespaces specified. Use --namespaces or provide config file with namespaces.")
    
    # Get threshold from config if not specified
    threshold = args.threshold
    if config.get('monitoring', {}).get('restart_threshold'):
        threshold = config['monitoring']['restart_threshold']
    
    def run_monitoring():
        """Run a single monitoring cycle"""
        # Create monitor instance
        monitor = KubernetesPodMonitor(namespaces, threshold, config)
        
        # Run monitoring
        logger.info("Starting Kubernetes pod restart monitoring...")
        alerts = monitor.monitor_all_namespaces()
        
        # Save results
        monitor.save_alerts_to_csv(args.output_csv)
        monitor.save_detailed_alerts_to_json(args.output_json)
        monitor.save_statistics_to_json(args.stats_json)
        
        # Print results
        monitor.print_statistics()
        
        if not args.quiet:
            monitor.print_alerts_summary()
        
        # Final summary
        logger.info(f"Monitoring complete. Evaluated {monitor.statistics['total_pods_evaluated']} pods "
                   f"across {monitor.statistics['accessible_namespaces']} namespaces. "
                   f"Found {len(alerts)} alerts ({monitor.statistics['new_alerts']} new).")
        
        return len(alerts)
    
    if args.watch:
        logger.info(f"Starting watch mode - monitoring every {args.watch_interval} seconds")
        try:
            while True:
                alert_count = run_monitoring()
                print(f"\n💤 Sleeping for {args.watch_interval} seconds... (Ctrl+C to stop)")
                time.sleep(args.watch_interval)
        except KeyboardInterrupt:
            logger.info("Watch mode stopped by user")
            sys.exit(0)
    else:
        # Single run
        alert_count = run_monitoring()
        sys.exit(1 if alert_count > 0 else 0)

if __name__ == "__main__":
    main()
