import argparse
import logging
from kubernetes import client, config
import urllib3
import requests
import json
from tabulate import tabulate
from datetime import datetime
import time

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ANSI colors for beautiful output
class C:
    B = '\033[1m'  # Bold
    G = '\033[92m'  # Green
    Y = '\033[93m'  # Yellow  
    R = '\033[91m'  # Red
    C = '\033[96m'  # Cyan
    E = '\033[0m'   # End

def print_section(title, char='─'):
    print(f"\n{C.B}{C.C}{title}{C.E}\n{C.C}{char * 70}{C.E}")

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
                                    'endpoint': f"https://{rule.host}{health_path}",
                                    'probe_type': 'health_check'
                                }
                                found_ingress = True
                                break
                        if found_ingress: break
                    if found_ingress: break
        
        if not found_ingress and health_path:
            services_without_health.append(f"{svc_name} (no ingress route)")
    
    return list(health_endpoints.values()), services_without_health

def check_health_status(endpoints):
    print_section("🔍 Health Status Verification")
    print(f"{C.C}Checking {len(endpoints)} endpoints...{C.E}\n")
    
    results = []
    for i, ep in enumerate(endpoints, 1):
        service_name, endpoint_url = ep['service'], ep['endpoint']
        print(f"{C.B}[{i:2d}/{len(endpoints)}]{C.E} {C.C}Testing{C.E} {service_name:<25}", end=' ')
        
        try:
            start_time = time.time()
            response = requests.get(endpoint_url, timeout=10, verify=False, headers={'Accept': 'application/json'})
            response_time = time.time() - start_time
            
            if response.status_code == 200:
                try:
                    status = response.json().get('status', 'UNKNOWN')
                    if status == 'UP':
                        print(f"{C.G}✅ HEALTHY{C.E} ({response_time:.2f}s)")
                        health_status = '🟢 HEALTHY'
                    else:
                        print(f"{C.Y}⚠️  DEGRADED{C.E} ({response_time:.2f}s)")
                        health_status = '🟡 DEGRADED'
                except json.JSONDecodeError:
                    print(f"{C.R}❌ INVALID JSON{C.E} ({response_time:.2f}s)")
                    status, health_status = 'INVALID_JSON', '🟡 WARNING'
            else:
                print(f"{C.R}❌ HTTP {response.status_code}{C.E} ({response_time:.2f}s)")
                status, health_status = f'HTTP_{response.status_code}', '🔴 UNHEALTHY'
            
            results.append({
                'Service': service_name, 'Status': status, 'HTTP Code': response.status_code,
                'Response Time': f"{response_time:.2f}s", 'Health': health_status
            })
            
        except requests.exceptions.Timeout:
            print(f"{C.R}⏱️  TIMEOUT{C.E} (>10s)")
            results.append({'Service': service_name, 'Status': 'TIMEOUT', 'HTTP Code': 'N/A', 
                          'Response Time': '>10s', 'Health': '🔴 TIMEOUT'})
        except requests.exceptions.ConnectionError:
            print(f"{C.R}🚫 UNREACHABLE{C.E}")
            results.append({'Service': service_name, 'Status': 'CONNECTION_ERROR', 'HTTP Code': 'N/A',
                          'Response Time': 'N/A', 'Health': '🔴 UNREACHABLE'})
        except Exception as e:
            print(f"{C.R}💥 ERROR{C.E}")
            results.append({'Service': service_name, 'Status': f'ERROR: {str(e)[:30]}', 'HTTP Code': 'N/A',
                          'Response Time': 'N/A', 'Health': '🔴 ERROR'})
    
    return results

def print_results(endpoints, health_results, services_without_health, namespace):
    # Print discovered endpoints
    print_section(f"📍 Discovered Health Endpoints in '{namespace}'")
    if endpoints:
        print(f"{C.G}✅ Found {len(endpoints)} valid health check endpoints:{C.E}\n")
        endpoint_data = [[f"{i:2d}", ep['service'], ep['endpoint']] for i, ep in enumerate(endpoints, 1)]
        print(tabulate(endpoint_data, headers=['#', 'Service Name', 'Health Endpoint'], 
                      tablefmt='fancy_grid', maxcolwidths=[3, 25, 60]))
    else:
        print(f"{C.Y}⚠️  No valid health check endpoints found{C.E}")
        return
    
    # Print health check results
    print_section("📊 Health Check Results")
    table_data = [[r['Service'], r['Status'], r['HTTP Code'], r['Response Time'], r['Health']] 
                  for r in health_results]
    print(tabulate(table_data, headers=['Service Name', 'Status', 'HTTP Code', 'Response Time', 'Health'],
                  tablefmt='fancy_grid', maxcolwidths=[20, 15, 10, 12, 15]))
    
    # Health summary
    healthy_count = sum(1 for r in health_results if r['Status'] == 'UP')
    success_rate = (healthy_count/len(health_results))*100
    print_section("🏥 Health Summary")
    
    summary_data = [
        ['📊 Total Endpoints', len(health_results)],
        ['🟢 Healthy Services', f"{healthy_count} ({success_rate:.1f}%)"],
        ['🔴 Unhealthy Services', f"{len(health_results) - healthy_count} ({100-success_rate:.1f}%)"],
        ['📈 Success Rate', f"{success_rate:.1f}%"]
    ]
    print(tabulate(summary_data, tablefmt='fancy_grid', colalign=['left', 'center']))
    
    # Status indicator
    if success_rate >= 90:
        print(f"\n{C.G}🎉 Excellent! System health is optimal.{C.E}")
    elif success_rate >= 70:
        print(f"\n{C.Y}⚠️  Good health, but some services need attention.{C.E}")
    else:
        print(f"\n{C.R}🚨 Warning! Multiple services are experiencing issues.{C.E}")
    
    # Services without health endpoints
    if services_without_health:
        print_section(f"❌ Services Without Health Endpoints ({len(services_without_health)})")
        for svc in services_without_health:
            print(f"   • {svc}")
    
    # Overall summary
    print_section("📋 Overall Summary")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total_services = len(endpoints) + len(services_without_health)
    
    overall_data = [
        ['🔍 Scan Timestamp', timestamp],
        ['📦 Total Services', total_services],
        ['✅ Services with Health Endpoints', len(endpoints)],
        ['❌ Services without Health Endpoints', len(services_without_health)],
        ['🟢 Currently Healthy', healthy_count],
        ['🔴 Currently Unhealthy', len(health_results) - healthy_count]
    ]
    print(tabulate(overall_data, tablefmt='fancy_grid', colalign=['left', 'center']))

if __name__ == "__main__":
    # Startup banner
    print(f"\n{C.B}{C.C}{'═' * 80}{C.E}")
    print(f"{C.B}{C.C}{'🏥 KUBERNETES HEALTH CHECK MONITOR 🏥'.center(80)}{C.E}")
    print(f"{C.B}{C.C}{'═' * 80}{C.E}")
    print(f"{C.C}Real-time health monitoring for your Kubernetes services{C.E}")
    
    parser = argparse.ArgumentParser(description="Fetch health check endpoints from Kubernetes services.")
    parser.add_argument("namespace", help="Kubernetes namespace to query")
    args = parser.parse_args()
    
    print(f"\n{C.B}🎯 Target Namespace: {C.G}{args.namespace}{C.E}")
    
    try:
        endpoints, services_without_health = get_health_check_endpoints(args.namespace)
        health_results = check_health_status(endpoints) if endpoints else []
        print_results(endpoints, health_results, services_without_health, args.namespace)
        print(f"\n{C.B}{C.G}✨ Health check completed successfully! ✨{C.E}")
    except Exception as e:
        print(f"{C.R}❌ Failed to complete health check: {str(e)}{C.E}")
        import traceback
        traceback.print_exc()
