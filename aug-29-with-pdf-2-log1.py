import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import requests
import urllib3
from kubernetes import client, config
from tabulate import tabulate

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ANSI Colors
class Colors:
    GREEN = '\033[92m'
    YELLOW = '\033[93m'  
    RED = '\033[91m'
    CYAN = '\033[96m'
    BOLD = '\033[1m'
    END = '\033[0m'

class K8sHealthChecker:
    """Main health checker class"""
    
    def __init__(self, namespace, output_dir="reports"):
        self.namespace = namespace
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.timestamp = datetime.now()
        
        # Initialize Kubernetes clients
        config.load_kube_config()
        self.v1 = client.CoreV1Api()
        self.networking_v1 = client.NetworkingV1Api()
    
    def analyze_pod_logs(self, pod_name, container_name=None):
        """Enhanced log analysis for restart loop detection"""
        try:
            # Get current and previous logs
            current_logs = self._get_container_logs(pod_name, container_name, previous=False)
            previous_logs = self._get_container_logs(pod_name, container_name, previous=True)
            
            # Choose best log source
            if previous_logs and len(previous_logs) > len(current_logs or ""):
                log_response = previous_logs
                log_source = "previous"
            else:
                log_response = current_logs or ""
                log_source = "current"
            
            if not log_response.strip():
                return "No logs available for analysis"
            
            # Analyze logs for errors
            return self._analyze_log_content(log_response, log_source)
            
        except Exception as e:
            return f"Log analysis failed: {str(e)}"
    
    def _get_container_logs(self, pod_name, container_name=None, previous=False):
        """Get container logs"""
        try:
            kwargs = {
                'name': pod_name,
                'namespace': self.namespace,
                'tail_lines': 100,
                'previous': previous
            }
            if container_name:
                kwargs['container'] = container_name
                
            return self.v1.read_namespaced_pod_log(**kwargs)
        except:
            return None
    
    def _analyze_log_content(self, log_content, log_source):
        """Analyze log content for specific error patterns"""
        lines = log_content.strip().split('\n')
        
        error_patterns = {
            'OutOfMemoryError': [r'OutOfMemoryError', r'out of memory', r'oom.*killed'],
            'Port Already in Use': [r'Port \d+ is already in use', r'address already in use'],
            'Database Connection': [r'Connection refused.*:\d+', r'Database connection failed'],
            'Configuration Error': [r'Configuration.*error', r'Missing.*configuration'],
            'Permission Denied': [r'Permission denied', r'Access denied'],
            'File Not Found': [r'No such file or directory', r'FileNotFoundException'],
            'Application Startup': [r'Application failed to start', r'Startup.*failed'],
            'SSL/TLS Issues': [r'ssl.*handshake.*failed', r'certificate.*verification.*failed']
        }
        
        # Check recent lines for errors
        recent_lines = lines[-30:]
        for line in reversed(recent_lines):
            line_clean = line.strip()
            if not line_clean:
                continue
                
            for error_type, patterns in error_patterns.items():
                for pattern in patterns:
                    if re.search(pattern, line_clean, re.IGNORECASE):
                        # Truncate long lines
                        if len(line_clean) > 120:
                            line_clean = line_clean[:120] + "..."
                        return f"{error_type}: {line_clean} ({log_source} logs)"
        
        # General error detection
        for line in reversed(recent_lines):
            if any(kw in line.lower() for kw in ['fatal', 'error', 'exception', 'failed']):
                clean_line = line.strip()
                if len(clean_line) > 150:
                    clean_line = clean_line[:150] + "..."
                return f"Critical Error: {clean_line} ({log_source} logs)"
        
        return f"Restart detected - no specific error pattern found ({log_source} logs)"
    
    def get_restart_loop_info(self, pod, container):
        """Get detailed restart loop information"""
        pod_name = pod.metadata.name
        container_name = container.name
        
        restart_info = {
            'restart_count': container.restart_count,
            'current_state': 'Unknown',
            'exit_code': None,
            'exact_error': None
        }
        
        # Analyze container state
        if container.state:
            if container.state.waiting:
                restart_info['current_state'] = container.state.waiting.reason
                if container.state.waiting.message:
                    restart_info['exact_error'] = container.state.waiting.message
            elif container.state.terminated:
                restart_info['current_state'] = 'Terminated'
                restart_info['exit_code'] = container.state.terminated.exit_code
                if container.state.terminated.message:
                    restart_info['exact_error'] = container.state.terminated.message
        
        # Get log analysis
        log_analysis = self.analyze_pod_logs(pod_name, container_name)
        
        return restart_info, log_analysis
    
    def analyze_pod_fault(self, pod):
        """Analyze pod faults with restart loop focus"""
        pod_name = pod.metadata.name
        reasons = []
        root_cause = None
        is_restart_loop = False
        
        # Check pod phase
        if pod.status.phase in ['Failed', 'Pending']:
            reasons.append(f"Phase: {pod.status.phase}")
        
        # Analyze containers
        if pod.status.container_statuses:
            for container in pod.status.container_statuses:
                container_name = container.name
                restart_count = container.restart_count
                
                # Crash loop detection
                if (container.state and container.state.waiting and 
                    container.state.waiting.reason == 'CrashLoopBackOff'):
                    
                    is_restart_loop = True
                    restart_info, log_analysis = self.get_restart_loop_info(pod, container)
                    
                    analysis_parts = [f"Restart Count: {restart_count}"]
                    if restart_info['exit_code']:
                        analysis_parts.append(f"Exit Code: {restart_info['exit_code']}")
                    if log_analysis and "no specific error pattern found" not in log_analysis:
                        analysis_parts.append(f"Analysis: {log_analysis}")
                    
                    root_cause = f"RESTART LOOP: {' | '.join(analysis_parts)}"
                    
                # High restart count
                elif restart_count >= 5:
                    is_restart_loop = True
                    restart_info, log_analysis = self.get_restart_loop_info(pod, container)
                    root_cause = f"FREQUENT RESTARTS: Count: {restart_count} | {log_analysis}"
                
                # Other error states
                elif (container.state and container.state.waiting and 
                      container.state.waiting.reason in ['ImagePullBackOff', 'ErrImagePull']):
                    error_msg = container.state.waiting.message or "Image pull failed"
                    root_cause = f"IMAGE ERROR: {error_msg[:150]}"
        
        return {
            'name': pod_name,
            'reasons': reasons,
            'root_cause': root_cause,
            'is_restart_loop': is_restart_loop
        }
    
    def get_service_endpoints(self):
        """Get service endpoints and categorize them"""
        services = self.v1.list_namespaced_service(self.namespace)
        pods = self.v1.list_namespaced_pod(self.namespace)
        ingresses = self.networking_v1.list_namespaced_ingress(self.namespace)
        
        health_endpoints = []
        basic_endpoints = []
        services_no_selector = []
        services_no_health_probe = []
        services_no_ingress = []
        suspended_services = []
        
        for svc in services.items:
            svc_name = svc.metadata.name
            selector = svc.spec.selector
            
            if not selector:
                services_no_selector.append(svc_name)
                continue
            
            # Get matching pods and analyze faults
            matching_pods = [p for p in pods.items 
                           if all((p.metadata.labels or {}).get(k) == v 
                                 for k, v in selector.items())]
            
            total_pods = len(matching_pods)
            if total_pods == 0:
                suspended_services.append(svc_name)
                continue
            
            # Analyze faulty pods
            faulty_pods = []
            restart_loop_pods = []
            
            for pod in matching_pods:
                if self._is_pod_faulty(pod):
                    fault_analysis = self.analyze_pod_fault(pod)
                    faulty_pods.append(fault_analysis)
                    if fault_analysis['is_restart_loop']:
                        restart_loop_pods.append(pod.metadata.name)
            
            # Find health probes and ingress
            health_path = self._find_health_probe(matching_pods)
            ingress_endpoint = self._find_ingress_endpoint(ingresses, svc_name)
            
            service_data = {
                'service': svc_name,
                'total_pods': total_pods,
                'faulty_pods': faulty_pods,
                'restart_loop_pods': restart_loop_pods
            }
            
            if health_path and ingress_endpoint:
                service_data['endpoint'] = f"{ingress_endpoint}{health_path}"
                health_endpoints.append(service_data)
            elif ingress_endpoint:
                service_data['endpoint'] = ingress_endpoint
                basic_endpoints.append(service_data)
            elif health_path:
                services_no_ingress.append(svc_name)
            else:
                services_no_health_probe.append(svc_name)
        
        return {
            'health_endpoints': health_endpoints,
            'basic_endpoints': basic_endpoints,
            'services_no_selector': services_no_selector,
            'services_no_health_probe': services_no_health_probe,
            'services_no_ingress': services_no_ingress,
            'suspended_services': suspended_services
        }
    
    def _is_pod_faulty(self, pod):
        """Check if pod is faulty"""
        if pod.status.phase in ['Failed', 'Pending']:
            return True
        
        if pod.status.container_statuses:
            for container in pod.status.container_statuses:
                if (container.state and container.state.waiting and 
                    container.state.waiting.reason in ['CrashLoopBackOff', 'ImagePullBackOff', 'ErrImagePull']):
                    return True
                if container.restart_count >= 3:
                    return True
        
        return False
    
    def _find_health_probe(self, pods):
        """Find health probe path in pods"""
        for pod in pods:
            for container in pod.spec.containers:
                for probe in [container.liveness_probe, container.readiness_probe]:
                    if probe and probe.http_get and probe.http_get.path:
                        path = probe.http_get.path
                        if "/actuator/health" in path or path in ["/ping", "/health"]:
                            return path
        return None
    
    def _find_ingress_endpoint(self, ingresses, service_name):
        """Find ingress endpoint for service"""
        for ingress in ingresses.items:
            if ingress.spec.rules:
                for rule in ingress.spec.rules:
                    if rule.host and rule.http and rule.http.paths:
                        for path in rule.http.paths:
                            if (path.backend.service and 
                                path.backend.service.name == service_name):
                                return f"https://{rule.host}"
        return None
    
    def check_health_endpoints(self, endpoints):
        """Check health endpoints"""
        results = []
        healthy_count = 0
        
        print(f"\n{Colors.BOLD}{Colors.CYAN}Health Check: {self.namespace} ({len(endpoints)} endpoints){Colors.END}")
        print(f"{Colors.CYAN}{'─' * 70}{Colors.END}")
        
        for i, ep in enumerate(endpoints, 1):
            service_name = ep['service']
            endpoint_url = ep['endpoint']
            faulty_pods = ep['faulty_pods']
            restart_loops = ep['restart_loop_pods']
            
            print(f"[{i}/{len(endpoints)}] {service_name:<20}", end=' ')
            
            try:
                response = requests.get(endpoint_url, timeout=8, verify=False)
                
                if response.status_code == 200:
                    try:
                        health_data = response.json()
                        status = health_data.get('status', 'UP')
                    except:
                        status = 'UP'
                    
                    if status == 'UP':
                        print(f"{Colors.GREEN}✓ UP{Colors.END}")
                        health_status = 'UP'
                        healthy_count += 1
                    else:
                        print(f"{Colors.YELLOW}⚠ {status}{Colors.END}")
                        health_status = status
                else:
                    print(f"{Colors.RED}✗ HTTP {response.status_code}{Colors.END}")
                    health_status = f'HTTP {response.status_code}'
                
            except requests.exceptions.Timeout:
                print(f"{Colors.RED}✗ TIMEOUT{Colors.END}")
                health_status = 'TIMEOUT'
            except:
                print(f"{Colors.RED}✗ UNREACHABLE{Colors.END}")
                health_status = 'UNREACHABLE'
            
            # Show restart loop details
            if restart_loops:
                print(f"\n    🔄 RESTART LOOPS: {len(restart_loops)} pods")
                for fault in faulty_pods:
                    if fault['is_restart_loop']:
                        print(f"       {fault['name']}: {fault['root_cause']}")
            
            results.append({
                'service': service_name,
                'status': health_status,
                'pods': ep['total_pods'],
                'faulty_pods': faulty_pods,
                'restart_loops': restart_loops
            })
        
        return results, healthy_count
    
    def check_basic_connectivity(self, endpoints):
        """Check basic connectivity"""
        results = []
        
        if not endpoints:
            return results
        
        print(f"\n{Colors.BOLD}{Colors.CYAN}Basic Connectivity: {self.namespace} ({len(endpoints)} services){Colors.END}")
        print(f"{Colors.CYAN}{'─' * 70}{Colors.END}")
        
        for i, ep in enumerate(endpoints, 1):
            service_name = ep['service']
            endpoint_url = ep['endpoint']
            faulty_pods = ep['faulty_pods']
            restart_loops = ep['restart_loop_pods']
            
            print(f"[{i}/{len(endpoints)}] {service_name:<20}", end=' ')
            
            try:
                response = requests.get(endpoint_url, timeout=5, verify=False)
                if 200 <= response.status_code < 500:
                    print(f"{Colors.GREEN}✓ ACCESSIBLE{Colors.END}")
                    status = 'ACCESSIBLE'
                else:
                    print(f"{Colors.RED}✗ HTTP {response.status_code}{Colors.END}")
                    status = f'HTTP {response.status_code}'
            except:
                print(f"{Colors.RED}✗ UNREACHABLE{Colors.END}")
                status = 'UNREACHABLE'
            
            # Show restart loop details
            if restart_loops:
                print(f"\n    🔄 RESTART LOOPS: {len(restart_loops)} pods")
                for fault in faulty_pods:
                    if fault['is_restart_loop']:
                        print(f"       {fault['name']}: {fault['root_cause']}")
            
            results.append({
                'service': service_name,
                'status': status,
                'pods': ep['total_pods'],
                'faulty_pods': faulty_pods,
                'restart_loops': restart_loops
            })
        
        return results
    
    def generate_html_report(self, data, filename=None):
        """Generate HTML report"""
        if not filename:
            timestamp = self.timestamp.strftime('%Y%m%d_%H%M%S')
            filename = f"k8s_health_report_{self.namespace}_{timestamp}.html"
        
        filepath = self.output_dir / filename
        
        html_content = self._create_html_content(data)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        print(f"{Colors.GREEN}✓ HTML report generated: {filepath}{Colors.END}")
        return str(filepath)
    
    def _create_html_content(self, data):
        """Create HTML content"""
        health_results = data['health_results']
        basic_results = data['basic_results']
        categories = data['categories']
        
        # Calculate statistics
        total_health = len(health_results)
        total_basic = len(basic_results)
        healthy_count = sum(1 for r in health_results if r['status'] == 'UP')
        accessible_count = sum(1 for r in basic_results if r['status'] == 'ACCESSIBLE')
        
        active_services = total_health + total_basic
        total_healthy = healthy_count + accessible_count
        health_rate = (total_healthy / active_services * 100) if active_services > 0 else 0
        
        # Determine overall status
        if health_rate >= 95:
            status_class = "excellent"
            status_text = "EXCELLENT"
        elif health_rate >= 85:
            status_class = "healthy"
            status_text = "HEALTHY"
        elif health_rate >= 70:
            status_class = "degraded"
            status_text = "DEGRADED"
        else:
            status_class = "critical"
            status_text = "CRITICAL"
        
        html_template = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>K8s Health Report - {self.namespace}</title>
    <style>
        body {{ font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; margin: 0; padding: 20px; background-color: #f5f5f5; }}
        .container {{ max-width: 1200px; margin: 0 auto; background: white; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
        .header {{ background: #e20074; color: white; padding: 20px; border-radius: 8px 8px 0 0; text-align: center; }}
        .header h1 {{ margin: 0; font-size: 2em; }}
        .header p {{ margin: 5px 0 0 0; opacity: 0.9; }}
        .content {{ padding: 20px; }}
        .status-overview {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin-bottom: 30px; }}
        .status-card {{ padding: 20px; border-radius: 6px; text-align: center; }}
        .status-card.excellent {{ background: #d4edda; border: 1px solid #c3e6cb; }}
        .status-card.healthy {{ background: #d4edda; border: 1px solid #c3e6cb; }}
        .status-card.degraded {{ background: #fff3cd; border: 1px solid #ffeaa7; }}
        .status-card.critical {{ background: #f8d7da; border: 1px solid #f5c6cb; }}
        .status-card h3 {{ margin: 0 0 10px 0; font-size: 1.2em; }}
        .status-card .value {{ font-size: 2em; font-weight: bold; margin: 10px 0; }}
        .section {{ margin-bottom: 30px; }}
        .section h2 {{ color: #e20074; border-bottom: 2px solid #e20074; padding-bottom: 10px; }}
        .table {{ width: 100%; border-collapse: collapse; margin-top: 15px; }}
        .table th, .table td {{ padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }}
        .table th {{ background-color: #e20074; color: white; }}
        .table tr:nth-child(even) {{ background-color: #f8f9fa; }}
        .status-up {{ color: #28a745; font-weight: bold; }}
        .status-down {{ color: #dc3545; font-weight: bold; }}
        .status-warning {{ color: #ffc107; font-weight: bold; }}
        .restart-loop {{ background-color: #fff3cd; padding: 8px; border-radius: 4px; margin: 4px 0; }}
        .restart-loop-icon {{ color: #856404; }}
        .error-details {{ font-family: monospace; font-size: 0.9em; background: #f8f9fa; padding: 8px; border-radius: 4px; }}
        .service-list {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 10px; }}
        .service-item {{ background: #f8f9fa; padding: 10px; border-radius: 4px; border-left: 4px solid #e20074; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Kubernetes Health Report</h1>
            <p>Namespace: <strong>{self.namespace}</strong> | Generated: {self.timestamp.strftime('%Y-%m-%d %H:%M:%S')}</p>
        </div>
        
        <div class="content">
            <div class="status-overview">
                <div class="status-card {status_class}">
                    <h3>System Status</h3>
                    <div class="value">{status_text}</div>
                    <p>{health_rate:.1f}% Healthy</p>
                </div>
                <div class="status-card">
                    <h3>Active Services</h3>
                    <div class="value">{total_healthy}/{active_services}</div>
                    <p>Operational</p>
                </div>
                <div class="status-card">
                    <h3>Suspended Services</h3>
                    <div class="value">{len(categories['suspended_services'])}</div>
                    <p>Zero Pods</p>
                </div>
            </div>
        """
        
        # Health monitored services
        if health_results:
            html_template += f"""
            <div class="section">
                <h2>Health Monitored Services ({len(health_results)})</h2>
                <table class="table">
                    <thead>
                        <tr><th>Service</th><th>Status</th><th>Pods</th><th>Issues</th></tr>
                    </thead>
                    <tbody>
            """
            
            for result in health_results:
                status_class = "status-up" if result['status'] == 'UP' else "status-down"
                issues_html = ""
                
                if result['restart_loops']:
                    issues_html = f'<div class="restart-loop"><span class="restart-loop-icon">🔄</span> {len(result["restart_loops"])} restart loops</div>'
                    for fault in result['faulty_pods']:
                        if fault['is_restart_loop']:
                            issues_html += f'<div class="error-details">{fault["name"]}: {fault["root_cause"]}</div>'
                
                html_template += f"""
                        <tr>
                            <td>{result['service']}</td>
                            <td><span class="{status_class}">{result['status']}</span></td>
                            <td>{result['pods']}</td>
                            <td>{issues_html}</td>
                        </tr>
                """
            
            html_template += """
                    </tbody>
                </table>
            </div>
            """
        
        # Basic connectivity services
        if basic_results:
            html_template += f"""
            <div class="section">
                <h2>Basic Connectivity Services ({len(basic_results)})</h2>
                <table class="table">
                    <thead>
                        <tr><th>Service</th><th>Status</th><th>Pods</th><th>Issues</th></tr>
                    </thead>
                    <tbody>
            """
            
            for result in basic_results:
                status_class = "status-up" if result['status'] == 'ACCESSIBLE' else "status-down"
                issues_html = ""
                
                if result['restart_loops']:
                    issues_html = f'<div class="restart-loop"><span class="restart-loop-icon">🔄</span> {len(result["restart_loops"])} restart loops</div>'
                    for fault in result['faulty_pods']:
                        if fault['is_restart_loop']:
                            issues_html += f'<div class="error-details">{fault["name"]}: {fault["root_cause"]}</div>'
                
                html_template += f"""
                        <tr>
                            <td>{result['service']}</td>
                            <td><span class="{status_class}">{result['status']}</span></td>
                            <td>{result['pods']}</td>
                            <td>{issues_html}</td>
                        </tr>
                """
            
            html_template += """
                    </tbody>
                </table>
            </div>
            """
        
        # Service categories
        category_sections = [
            ('suspended_services', 'Suspended Services', 'Services with zero pods'),
            ('services_no_health_probe', 'Services Without Health Probes', 'Missing health monitoring'),
            ('services_no_ingress', 'Services Without Ingress', 'No external access'),
            ('services_no_selector', 'Services Without Selectors', 'Invalid configuration')
        ]
        
        for category_key, title, description in category_sections:
            services = categories.get(category_key, [])
            if services:
                html_template += f"""
            <div class="section">
                <h2>{title} ({len(services)})</h2>
                <p>{description}</p>
                <div class="service-list">
                """
                for service in services:
                    html_template += f'<div class="service-item">{service}</div>'
                
                html_template += """
                </div>
            </div>
                """
        
        html_template += """
        </div>
    </div>
</body>
</html>
        """
        
        return html_template

def print_console_results(health_results, basic_results, categories):
    """Print results to console"""
    # Health results
    if health_results:
        print(f"\n{Colors.BOLD}Health Check Results{Colors.END}")
        table_data = []
        for r in health_results:
            restart_info = f" ({len(r['restart_loops'])} restart loops)" if r['restart_loops'] else ""
            table_data.append([r['service'], r['status'], r['pods'], restart_info])
        
        print(tabulate(table_data, headers=['Service', 'Status', 'Pods', 'Issues'], tablefmt='simple'))
    
    # Basic connectivity results
    if basic_results:
        print(f"\n{Colors.BOLD}Basic Connectivity Results{Colors.END}")
        table_data = []
        for r in basic_results:
            restart_info = f" ({len(r['restart_loops'])} restart loops)" if r['restart_loops'] else ""
            table_data.append([r['service'], r['status'], r['pods'], restart_info])
        
        print(tabulate(table_data, headers=['Service', 'Status', 'Pods', 'Issues'], tablefmt='simple'))
    
    # Service categories
    for category_key, title in [
        ('suspended_services', 'Suspended Services'),
        ('services_no_health_probe', 'Services Without Health Probes'),
        ('services_no_ingress', 'Services Without Ingress'),
        ('services_no_selector', 'Services Without Selectors')
    ]:
        services = categories.get(category_key, [])
        if services:
            print(f"\n{Colors.YELLOW}{title} ({len(services)}):${Colors.END}")
            for svc in services:
                print(f"  • {svc}")

def main():
    parser = argparse.ArgumentParser(description="K8s health check with restart loop analysis")
    parser.add_argument("namespace", help="Kubernetes namespace")
    parser.add_argument("--output-format", choices=['console', 'html', 'both'], 
                       default='console', help="Output format")
    parser.add_argument("--output-dir", default="reports", help="Output directory")
    
    args = parser.parse_args()
    
    try:
        checker = K8sHealthChecker(args.namespace, args.output_dir)
        
        # Get service endpoints
        endpoints_data = checker.get_service_endpoints()
        
        # Check health endpoints
        health_results, healthy_count = checker.check_health_endpoints(endpoints_data['health_endpoints'])
        
        # Check basic connectivity
        basic_results = checker.check_basic_connectivity(endpoints_data['basic_endpoints'])
        
        # Prepare data for reporting
        report_data = {
            'health_results': health_results,
            'basic_results': basic_results,
            'categories': {
                'suspended_services': endpoints_data['suspended_services'],
                'services_no_health_probe': endpoints_data['services_no_health_probe'],
                'services_no_ingress': endpoints_data['services_no_ingress'],
                'services_no_selector': endpoints_data['services_no_selector']
            }
        }
        
        # Output results
        if args.output_format in ['console', 'both']:
            print_console_results(health_results, basic_results, report_data['categories'])
        
        if args.output_format in ['html', 'both']:
            checker.generate_html_report(report_data)
        
        print(f"\n{Colors.CYAN}✓ Completed at {datetime.now().strftime('%H:%M:%S')}{Colors.END}")
        
    except Exception as e:
        print(f"{Colors.RED}✗ Error: {str(e)}{Colors.END}")
        sys.exit(1)

if __name__ == "__main__":
    main()
