import argparse
from kubernetes import client, config
import urllib3
import requests
import json
from tabulate import tabulate
from datetime import datetime

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ANSI colors
class C:
    G = '\033[92m'  # Green
    Y = '\033[93m'  # Yellow  
    R = '\033[91m'  # Red
    C = '\033[96m'  # Cyan
    B = '\033[1m'   # Bold
    E = '\033[0m'   # End

def get_pod_stats(pods, selector):
    """Get pod statistics for a service"""
    matching_pods = [pod for pod in pods.items 
                    if all((pod.metadata.labels or {}).get(k) == v for k, v in selector.items())]
    
    total_pods = len(matching_pods)
    faulty_pod_names = []
    
    for pod in matching_pods:
        # Check for fault conditions
        is_faulty = False
        pod_name = pod.metadata.name
        
        # Check pod phase
        if pod.status.phase in ['Failed', 'Pending']:
            is_faulty = True
        
        # Check container states for actual problems
        if pod.status.container_statuses:
            for container in pod.status.container_statuses:
                # Only count as faulty if pod has restarts AND is currently not ready/running
                if container.restart_count > 3 and not container.ready:
                    is_faulty = True
                
                # Always count crash loop back off as faulty
                if (container.state and container.state.waiting and 
                    container.state.waiting.reason == 'CrashLoopBackOff'):
                    is_faulty = True
                
                # Count as faulty if container is not running (but not if just restarting)
                if (container.state and container.state.waiting and 
                    container.state.waiting.reason in ['ImagePullBackOff', 'ErrImagePull', 'CreateContainerConfigError']):
                    is_faulty = True
        
        if is_faulty:
            faulty_pod_names.append(pod_name)
    
    return total_pods, faulty_pod_names, matching_pods

def get_health_check_endpoints(namespace):
    config.load_kube_config()
    v1, networking_v1 = client.CoreV1Api(), client.NetworkingV1Api()
    
    services = v1.list_namespaced_service(namespace)
    pods = v1.list_namespaced_pod(namespace)
    ingresses = networking_v1.list_namespaced_ingress(namespace)
    
    health_endpoints, services_without_health, suspended_services = {}, [], []
    
    for svc in services.items:
        svc_name = svc.metadata.name
        selector = svc.spec.selector
        
        if not selector:
            services_without_health.append(f"{svc_name} (no selector)")
            continue
        
        # Get pod statistics
        total_pods, faulty_pod_names, matching_pods = get_pod_stats(pods, selector)
        
        if total_pods == 0:
            suspended_services.append(svc_name)
            continue
            
        # Check for health probes
        health_path = None
        for pod in matching_pods:
            for container in pod.spec.containers:
                for probe in [container.liveness_probe, container.readiness_probe]:
                    if probe and probe.http_get and probe.http_get.path:
                        probe_path = probe.http_get.path
                        # Accept both actuator health endpoints and simple ping endpoints
                        if "/actuator/health" in probe_path or probe_path in ["/ping", "ping", "/health", "health"]:
                            health_path = probe_path
                            break
                if health_path:
                    break
            if health_path:
                break
        
        if not health_path:
            services_without_health.append(f"{svc_name} (no health probe)")
            continue
            
        # Find ingress endpoint
        found_ingress = False
        for ingress in ingresses.items:
            if ingress.spec.rules:
                for rule in ingress.spec.rules:
                    if rule.host and rule.http and rule.http.paths:
                        for path in rule.http.paths:
                            if path.backend.service and path.backend.service.name == svc_name:
                                health_endpoints[svc_name] = {
                                    'service': svc_name,
                                    'endpoint': f"https://{rule.host}{health_path}",
                                    'total_pods': total_pods,
                                    'faulty_pod_names': faulty_pod_names
                                }
                                found_ingress = True
                                break
                        if found_ingress: break
                    if found_ingress: break
        
        if not found_ingress and health_path:
            services_without_health.append(f"{svc_name} (no ingress route)")
    
    return list(health_endpoints.values()), services_without_health, suspended_services

def check_and_display_health(endpoints, namespace):
    print(f"\n{C.B}{C.C}🏥 Health Check: {namespace} ({len(endpoints)} endpoints){C.E}")
    print(f"{C.C}{'─' * 70}{C.E}")
    
    if not endpoints:
        print(f"{C.Y}⚠️  No health endpoints found{C.E}")
        return [], 0
    
    results = []
    healthy_count = 0
    
    # Check health and build results in one pass
    for i, ep in enumerate(endpoints, 1):
        service_name = ep['service']
        endpoint_url = ep['endpoint']
        total_pods = ep['total_pods']
        faulty_pod_names = ep['faulty_pod_names']
        
        print(f"[{i}/{len(endpoints)}] {service_name:<20}", end=' ')
        
        try:
            response = requests.get(endpoint_url, timeout=8, verify=False, headers={'Accept': 'application/json'})
            
            if response.status_code == 200:
                try:
                    health_data = response.json()
                    
                    # Handle different response formats
                    if 'status' in health_data:
                        # Standard actuator format: {"status": "UP"}
                        status = health_data.get('status', 'UNKNOWN')
                    elif 'pong' in health_data:
                        # Ping format: {"pong": true}
                        status = 'UP' if health_data.get('pong') else 'DOWN'
                    else:
                        # Unknown format but 200 OK
                        status = 'UP'
                    
                    if status == 'UP':
                        print(f"{C.G}✅ UP{C.E}")
                        health_status, healthy_count = '🟢 UP', healthy_count + 1
                    else:
                        print(f"{C.Y}⚠️  {status}{C.E}")
                        health_status = f'🟡 {status}'
                except json.JSONDecodeError:
                    print(f"{C.R}❌ INVALID JSON{C.E}")
                    status, health_status = 'INVALID_JSON', '🟡 WARNING'
            else:
                print(f"{C.R}❌ HTTP {response.status_code}{C.E}")
                status, health_status = f'HTTP_{response.status_code}', '🔴 ERROR'
            
            # Format faulty pod names with count
            if faulty_pod_names:
                fault_count = len(faulty_pod_names)
                faulty_display = f"{C.R}{fault_count}: {', '.join(faulty_pod_names)}{C.E}"
            else:
                faulty_display = f"{C.G}0: None{C.E}"
            
            results.append([service_name, health_status, str(total_pods), faulty_display])
            
        except requests.exceptions.Timeout:
            print(f"{C.R}⏱️  TIMEOUT{C.E}")
            fault_count = len(faulty_pod_names)
            faulty_display = f"{C.R}{fault_count}: {', '.join(faulty_pod_names)}{C.E}" if faulty_pod_names else f"{C.G}0: None{C.E}"
            results.append([service_name, '🔴 TIMEOUT', str(total_pods), faulty_display])
        except requests.exceptions.ConnectionError:
            print(f"{C.R}🚫 UNREACHABLE{C.E}")
            fault_count = len(faulty_pod_names)
            faulty_display = f"{C.R}{fault_count}: {', '.join(faulty_pod_names)}{C.E}" if faulty_pod_names else f"{C.G}0: None{C.E}"
            results.append([service_name, '🔴 UNREACHABLE', str(total_pods), faulty_display])
        except Exception as e:
            print(f"{C.R}💥 ERROR{C.E}")
            fault_count = len(faulty_pod_names)
            faulty_display = f"{C.R}{fault_count}: {', '.join(faulty_pod_names)}{C.E}" if faulty_pod_names else f"{C.G}0: None{C.E}"
            results.append([service_name, '🔴 ERROR', str(total_pods), faulty_display])
    
    return results, healthy_count

def print_compact_summary(results, healthy_count, services_without_health, suspended_services, namespace):
    total_endpoints = len(results)
    success_rate = (healthy_count/total_endpoints)*100 if total_endpoints > 0 else 0
    
    print(f"\n{C.B}📊 Results Summary{C.E}")
    print(tabulate(results, headers=['Service', 'Status', 'Total Pods', 'Faulty Pods'], tablefmt='simple'))
    
    # Compact stats
    print(f"\n{C.B}Stats:{C.E} {C.G}{healthy_count}/{total_endpoints} healthy{C.E} ({success_rate:.0f}%) ", end='')
    
    if services_without_health:
        print(f"| {C.Y}{len(services_without_health)} without health checks{C.E}")
        if len(services_without_health) <= 5:  # Only show if few
            for svc in services_without_health:
                print(f"  • {svc}")
    else:
        print()
    
    # Suspended services section
    if suspended_services:
        print(f"\n{C.B}🛑 Suspended Services (0 pods):{C.E}")
        for svc in suspended_services:
            print(f"  • {C.R}{svc}{C.E}")
    
    # Quick status
    if success_rate >= 90:
        print(f"\n{C.G}🎉 System healthy{C.E}")
    elif success_rate >= 70:
        print(f"\n{C.Y}⚠️  Some issues detected{C.E}")
    else:
        print(f"\n{C.R}🚨 Multiple services down{C.E}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="K8s health check monitor")
    parser.add_argument("namespace", help="Kubernetes namespace")
    args = parser.parse_args()
    
    try:
        endpoints, services_without_health, suspended_services = get_health_check_endpoints(args.namespace)
        results, healthy_count = check_and_display_health(endpoints, args.namespace)
        print_compact_summary(results, healthy_count, services_without_health, suspended_services, args.namespace)
        
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"\n{C.C}✨ Completed at {timestamp}{C.E}")
        
    except Exception as e:
        print(f"{C.R}❌ Error: {str(e)}{C.E}")
