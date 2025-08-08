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
    
    health_endpoints = {}
    services_no_selector = []
    services_no_pods = []
    services_no_health_probe = []
    services_no_ingress = []
    services_with_basic_endpoint = {}  # Services with ingress but no health probe
    suspended_services = []
    
    for svc in services.items:
        svc_name = svc.metadata.name
        selector = svc.spec.selector
        
        if not selector:
            services_no_selector.append(svc_name)
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
        
        # Find ingress endpoint
        ingress_endpoint = None
        for ingress in ingresses.items:
            if ingress.spec.rules:
                for rule in ingress.spec.rules:
                    if rule.host and rule.http and rule.http.paths:
                        for path in rule.http.paths:
                            if path.backend.service and path.backend.service.name == svc_name:
                                ingress_endpoint = f"https://{rule.host}"
                                break
                        if ingress_endpoint: break
                    if ingress_endpoint: break
        
        if health_path and ingress_endpoint:
            # Service has both health probe and ingress
            health_endpoints[svc_name] = {
                'service': svc_name,
                'endpoint': f"{ingress_endpoint}{health_path}",
                'total_pods': total_pods,
                'faulty_pod_names': faulty_pod_names
            }
        elif ingress_endpoint and not health_path:
            # Service has ingress but no health probe - test basic connectivity
            services_with_basic_endpoint[svc_name] = {
                'service': svc_name,
                'endpoint': ingress_endpoint,
                'total_pods': total_pods,
                'faulty_pod_names': faulty_pod_names
            }
        elif health_path and not ingress_endpoint:
            # Service has health probe but no ingress
            services_no_ingress.append(svc_name)
        else:
            # Service has no health probe and no ingress
            services_no_health_probe.append(svc_name)
    
    return (list(health_endpoints.values()), 
            list(services_with_basic_endpoint.values()),
            services_no_selector, 
            services_no_pods, 
            services_no_health_probe,
            services_no_ingress,
            suspended_services)

def check_and_display_health(endpoints, namespace):
    """Check basic connectivity for services without health endpoints"""
    if not basic_endpoints:
        return []
    
    print(f"\n{C.B}{C.C}🌐 Basic Connectivity Check: {namespace} ({len(basic_endpoints)} services){C.E}")
    print(f"{C.C}{'─' * 70}{C.E}")
    
    results = []
    
    for i, ep in enumerate(basic_endpoints, 1):
        service_name = ep['service']
        endpoint_url = ep['endpoint']
        total_pods = ep['total_pods']
        faulty_pod_names = ep['faulty_pod_names']
        
        print(f"[{i}/{len(basic_endpoints)}] {service_name:<20}", end=' ')
        
        try:
            response = requests.get(endpoint_url, timeout=5, verify=False, allow_redirects=True)
            
            if response.status_code in [200, 301, 302, 403]:  # Accessible responses
                print(f"{C.G}✅ ACCESSIBLE{C.E}")
                connectivity_status = '🟢 ACCESSIBLE'
            elif response.status_code in [404]:
                print(f"{C.Y}⚠️  NOT FOUND{C.E}")
                connectivity_status = '🟡 NOT FOUND'
            else:
                print(f"{C.R}❌ HTTP {response.status_code}{C.E}")
                connectivity_status = f'🔴 HTTP {response.status_code}'
            
            # Format faulty pod names with count
            if faulty_pod_names:
                fault_count = len(faulty_pod_names)
                faulty_display = f"{C.R}{fault_count}: {', '.join(faulty_pod_names)}{C.E}"
            else:
                faulty_display = f"{C.G}0: None{C.E}"
            
            results.append([service_name, connectivity_status, str(total_pods), faulty_display])
            
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
    
    return results
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
                        # Ping format: {"pong": true} or {"pong": "true"}
                        pong_value = health_data.get('pong')
                        if pong_value is True or str(pong_value).lower() == 'true':
                            status = 'UP'
                        else:
                            status = 'DOWN'
                    else:
                        # Unknown JSON format but 200 OK, assume healthy
                        status = 'UP'
                    
                except json.JSONDecodeError:
                    # Not JSON (plain text, HTML, etc.) but 200 OK means service is up
                    status = 'UP'
                
                if status == 'UP':
                    print(f"{C.G}✅ UP{C.E}")
                    health_status, healthy_count = '🟢 UP', healthy_count + 1
                else:
                    print(f"{C.Y}⚠️  {status}{C.E}")
                    health_status = f'🟡 {status}'
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

def check_basic_connectivity(basic_endpoints, namespace):
    """Check basic connectivity for services without health endpoints"""
    if not basic_endpoints:
        return []
    
    print(f"\n{C.B}{C.C}🌐 Basic Connectivity Check: {namespace} ({len(basic_endpoints)} services){C.E}")
    print(f"{C.C}{'─' * 70}{C.E}")
    
    results = []
    
    for i, ep in enumerate(basic_endpoints, 1):
        service_name = ep['service']
        endpoint_url = ep['endpoint']
        total_pods = ep['total_pods']
        faulty_pod_names = ep['faulty_pod_names']
        
        print(f"[{i}/{len(basic_endpoints)}] {service_name:<20}", end=' ')
        
        try:
            response = requests.get(endpoint_url, timeout=5, verify=False, allow_redirects=True)
            
            if response.status_code in [200, 301, 302, 403]:  # Accessible responses
                print(f"{C.G}✅ ACCESSIBLE{C.E}")
                connectivity_status = '🟢 ACCESSIBLE'
            elif response.status_code in [404]:
                print(f"{C.Y}⚠️  NOT FOUND{C.E}")
                connectivity_status = '🟡 NOT FOUND'
            else:
                print(f"{C.R}❌ HTTP {response.status_code}{C.E}")
                connectivity_status = f'🔴 HTTP {response.status_code}'
            
            # Format faulty pod names with count
            if faulty_pod_names:
                fault_count = len(faulty_pod_names)
                faulty_display = f"{C.R}{fault_count}: {', '.join(faulty_pod_names)}{C.E}"
            else:
                faulty_display = f"{C.G}0: None{C.E}"
            
            results.append([service_name, connectivity_status, str(total_pods), faulty_display])
            
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
    
    return results

def print_compact_summary(health_results, healthy_count, basic_results, services_no_selector, services_no_pods, services_no_health_probe, services_no_ingress, suspended_services, namespace):
    # Health check results
    if health_results:
        total_endpoints = len(health_results)
        success_rate = (healthy_count/total_endpoints)*100 if total_endpoints > 0 else 0
        
        print(f"\n{C.B}📊 Health Check Results{C.E}")
        print(tabulate(health_results, headers=['Service', 'Status', 'Total Pods', 'Faulty Pods'], tablefmt='simple'))
        
        print(f"\n{C.B}Health Stats:{C.E} {C.G}{healthy_count}/{total_endpoints} healthy{C.E} ({success_rate:.0f}%)")
    
    # Basic connectivity results
    if basic_results:
        print(f"\n{C.B}🌐 Basic Connectivity Results{C.E}")
        print(tabulate(basic_results, headers=['Service', 'Status', 'Total Pods', 'Faulty Pods'], tablefmt='simple'))
        
        accessible_count = sum(1 for r in basic_results if 'ACCESSIBLE' in r[1])
        print(f"\n{C.B}Connectivity Stats:{C.E} {C.G}{accessible_count}/{len(basic_results)} accessible{C.E}")
    
    # Services categorization
    print(f"\n{C.B}📋 Service Categories{C.E}")
    
    if suspended_services:
        print(f"\n{C.R}🛑 Suspended Services (0 pods): {len(suspended_services)}{C.E}")
        for svc in suspended_services[:5]:  # Show first 5
            print(f"  • {svc}")
        if len(suspended_services) > 5:
            print(f"  ... and {len(suspended_services)-5} more")
    
    if services_no_selector:
        print(f"\n{C.Y}🔸 No Selector: {len(services_no_selector)}{C.E}")
        for svc in services_no_selector[:3]:
            print(f"  • {svc}")
        if len(services_no_selector) > 3:
            print(f"  ... and {len(services_no_selector)-3} more")
    
    if services_no_health_probe:
        print(f"\n{C.Y}🔸 No Health Probe: {len(services_no_health_probe)}{C.E}")
        for svc in services_no_health_probe[:3]:
            print(f"  • {svc}")
        if len(services_no_health_probe) > 3:
            print(f"  ... and {len(services_no_health_probe)-3} more")
    
    if services_no_ingress:
        print(f"\n{C.Y}🔸 No Ingress Route: {len(services_no_ingress)}{C.E}")
        for svc in services_no_ingress[:3]:
            print(f"  • {svc}")
        if len(services_no_ingress) > 3:
            print(f"  ... and {len(services_no_ingress)-3} more")
    
    # Overall health status
    if health_results:
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
        (health_endpoints, basic_endpoints, services_no_selector, services_no_pods, 
         services_no_health_probe, services_no_ingress, suspended_services) = get_health_check_endpoints(args.namespace)
        
        # Check health endpoints
        health_results, healthy_count = check_and_display_health(health_endpoints, args.namespace)
        
        # Check basic connectivity for services without health probes
        basic_results = check_basic_connectivity(basic_endpoints, args.namespace)
        
        # Print comprehensive summary
        print_compact_summary(health_results, healthy_count, basic_results, 
                            services_no_selector, services_no_pods, services_no_health_probe, 
                            services_no_ingress, suspended_services, args.namespace)
        
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"\n{C.C}✨ Completed at {timestamp}{C.E}")
        
    except Exception as e:
        print(f"{C.R}❌ Error: {str(e)}{C.E}")
