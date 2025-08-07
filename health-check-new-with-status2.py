import argparse
from kubernetes import client, config
import urllib3
import requests
import json
from tabulate import tabulate
from datetime import datetime
import time

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ANSI colors
class C:
    G = '\033[92m'  # Green
    Y = '\033[93m'  # Yellow  
    R = '\033[91m'  # Red
    C = '\033[96m'  # Cyan
    B = '\033[1m'   # Bold
    E = '\033[0m'   # End

def get_health_check_endpoints(namespace):
    config.load_kube_config()
    v1, networking_v1 = client.CoreV1Api(), client.NetworkingV1Api()
    
    services = v1.list_namespaced_service(namespace)
    pods = v1.list_namespaced_pod(namespace)
    ingresses = networking_v1.list_namespaced_ingress(namespace)
    
    health_endpoints, services_without_health = {}, []
    
    for svc in services.items:
        svc_name = svc.metadata.name
        selector = svc.spec.selector
        
        if not selector:
            services_without_health.append(f"{svc_name} (no selector)")
            continue
            
        # Find matching pod
        matched_pod = next((pod for pod in pods.items 
                           if all((pod.metadata.labels or {}).get(k) == v for k, v in selector.items())), None)
        
        if not matched_pod:
            services_without_health.append(f"{svc_name} (no matching pods)")
            continue
            
        # Check for health probes
        health_path = None
        for container in matched_pod.spec.containers:
            for probe in [container.liveness_probe, container.readiness_probe]:
                if probe and probe.http_get and probe.http_get.path and "/actuator/health" in probe.http_get.path:
                    health_path = probe.http_get.path
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
                                    'endpoint': f"https://{rule.host}{health_path}"
                                }
                                found_ingress = True
                                break
                        if found_ingress: break
                    if found_ingress: break
        
        if not found_ingress and health_path:
            services_without_health.append(f"{svc_name} (no ingress route)")
    
    return list(health_endpoints.values()), services_without_health

def check_and_display_health(endpoints, namespace):
    print(f"\n{C.B}{C.C}🏥 Health Check: {namespace} ({len(endpoints)} endpoints){C.E}")
    print(f"{C.C}{'─' * 60}{C.E}")
    
    if not endpoints:
        print(f"{C.Y}⚠️  No health endpoints found{C.E}")
        return [], 0
    
    results = []
    healthy_count = 0
    
    # Check health and build results in one pass
    for i, ep in enumerate(endpoints, 1):
        service_name, endpoint_url = ep['service'], ep['endpoint']
        print(f"[{i}/{len(endpoints)}] {service_name:<20}", end=' ')
        
        try:
            start_time = time.time()
            response = requests.get(endpoint_url, timeout=8, verify=False, headers={'Accept': 'application/json'})
            response_time = time.time() - start_time
            
            if response.status_code == 200:
                try:
                    status = response.json().get('status', 'UNKNOWN')
                    if status == 'UP':
                        print(f"{C.G}✅ UP{C.E} ({response_time:.1f}s)")
                        health_status, healthy_count = '🟢 UP', healthy_count + 1
                    else:
                        print(f"{C.Y}⚠️  {status}{C.E} ({response_time:.1f}s)")
                        health_status = f'🟡 {status}'
                except json.JSONDecodeError:
                    print(f"{C.R}❌ INVALID JSON{C.E}")
                    status, health_status = 'INVALID_JSON', '🟡 WARNING'
            else:
                print(f"{C.R}❌ HTTP {response.status_code}{C.E}")
                status, health_status = f'HTTP_{response.status_code}', '🔴 ERROR'
            
            results.append([service_name, health_status, f"{response_time:.1f}s"])
            
        except requests.exceptions.Timeout:
            print(f"{C.R}⏱️  TIMEOUT{C.E}")
            results.append([service_name, '🔴 TIMEOUT', '>8s'])
        except requests.exceptions.ConnectionError:
            print(f"{C.R}🚫 UNREACHABLE{C.E}")
            results.append([service_name, '🔴 UNREACHABLE', 'N/A'])
        except Exception as e:
            print(f"{C.R}💥 ERROR{C.E}")
            results.append([service_name, '🔴 ERROR', 'N/A'])
    
    return results, healthy_count

def print_compact_summary(results, healthy_count, services_without_health, namespace):
    total_endpoints = len(results)
    success_rate = (healthy_count/total_endpoints)*100 if total_endpoints > 0 else 0
    
    print(f"\n{C.B}📊 Results Summary{C.E}")
    print(tabulate(results, headers=['Service', 'Status', 'Time'], tablefmt='simple'))
    
    # Compact stats
    print(f"\n{C.B}Stats:{C.E} {C.G}{healthy_count}/{total_endpoints} healthy{C.E} ({success_rate:.0f}%) ", end='')
    
    if services_without_health:
        print(f"| {C.Y}{len(services_without_health)} without health checks{C.E}")
        if len(services_without_health) <= 5:  # Only show if few
            for svc in services_without_health:
                print(f"  • {svc}")
    else:
        print()
    
    # Quick status
    if success_rate >= 90:
        print(f"{C.G}🎉 System healthy{C.E}")
    elif success_rate >= 70:
        print(f"{C.Y}⚠️  Some issues detected{C.E}")
    else:
        print(f"{C.R}🚨 Multiple services down{C.E}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="K8s health check monitor")
    parser.add_argument("namespace", help="Kubernetes namespace")
    args = parser.parse_args()
    
    try:
        endpoints, services_without_health = get_health_check_endpoints(args.namespace)
        results, healthy_count = check_and_display_health(endpoints, args.namespace)
        print_compact_summary(results, healthy_count, services_without_health, args.namespace)
        
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"\n{C.C}✨ Completed at {timestamp}{C.E}")
        
    except Exception as e:
        print(f"{C.R}❌ Error: {str(e)}{C.E}")
