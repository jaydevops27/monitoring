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

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_health_check_endpoints(namespace):
    # Load kubeconfig
    config.load_kube_config()
    
    v1 = client.CoreV1Api()
    networking_v1 = client.NetworkingV1Api()
    
    # Get services and pods
    services = v1.list_namespaced_service(namespace)
    pods = v1.list_namespaced_pod(namespace)
    
    health_endpoints = {}  # Use dict to avoid duplicates
    services_without_health = []  # Track services without health endpoints
    
    # Get all ingresses once to avoid repeated API calls
    ingresses = networking_v1.list_namespaced_ingress(namespace)
    
    for svc in services.items:
        svc_name = svc.metadata.name
        selector = svc.spec.selector
        if not selector:
            services_without_health.append(f"{svc_name} (no selector)")
            continue
            
        # Find one pod matching the service selector
        matched_pod = None
        for pod in pods.items:
            pod_labels = pod.metadata.labels or {}
            if all(pod_labels.get(k) == v for k, v in selector.items()):
                matched_pod = pod
                break
                
        if not matched_pod:
            services_without_health.append(f"{svc_name} (no matching pods)")
            continue
            
        # Check liveness and readiness probes for each container
        service_has_health_probe = False
        health_path = None
        
        for container in matched_pod.spec.containers:
            liveness = container.liveness_probe
            readiness = container.readiness_probe
            
            liveness_path = None
            readiness_path = None
            
            # Extract liveness probe path
            if liveness and liveness.http_get:
                liveness_path = liveness.http_get.path if liveness.http_get.path else None
                
            # Extract readiness probe path  
            if readiness and readiness.http_get:
                readiness_path = readiness.http_get.path if readiness.http_get.path else None
            
            # Only proceed if we have a valid health check path
            if liveness_path and readiness_path and liveness_path == readiness_path and "/actuator/health" in liveness_path:
                health_path = liveness_path
                service_has_health_probe = True
                break
            elif liveness_path and "/actuator/health" in liveness_path:
                health_path = liveness_path
                service_has_health_probe = True
                break
            elif readiness_path and "/actuator/health" in readiness_path:
                health_path = readiness_path
                service_has_health_probe = True
                break
        
        # Only create health endpoints if the service has valid health probes
        if service_has_health_probe and health_path:
            # Find the first matching ingress rule for this service
            found_ingress = False
            for ingress in ingresses.items:
                if ingress.spec.rules:
                    for rule in ingress.spec.rules:
                        if rule.host:
                            if rule.http and rule.http.paths:
                                for path in rule.http.paths:
                                    if (path.backend.service and 
                                        path.backend.service.name == svc_name):
                                        endpoint = f"https://{rule.host}{health_path}"
                                        # Store only one endpoint per service (first match)
                                        if svc_name not in health_endpoints:
                                            health_endpoints[svc_name] = {
                                                'service': svc_name,
                                                'endpoint': endpoint,
                                                'probe_type': 'health_check'
                                            }
                                            found_ingress = True
                                        break
                                if found_ingress:
                                    break
                        if found_ingress:
                            break
            
            # If service has health probe but no ingress, track it
            if not found_ingress:
                services_without_health.append(f"{svc_name} (no ingress route)")
        else:
            services_without_health.append(f"{svc_name} (no health probe)")
    
    return list(health_endpoints.values()), services_without_health

def check_health_status(endpoints):
    """Check the health status of each endpoint"""
    results = []
    
    print(f"\n🔍 Checking health status for {len(endpoints)} endpoints...")
    
    for i, ep in enumerate(endpoints, 1):
        service_name = ep['service']
        endpoint_url = ep['endpoint']
        
        print(f"  [{i}/{len(endpoints)}] Checking {service_name}...", end=' ')
        
        try:
            # Make HTTP request with timeout
            response = requests.get(
                endpoint_url, 
                timeout=10,
                verify=False,  # Skip SSL verification for internal services
                headers={'Accept': 'application/json'}
            )
            
            if response.status_code == 200:
                try:
                    health_data = response.json()
                    status = health_data.get('status', 'UNKNOWN')
                    print(f"✓")
                    
                    results.append({
                        'Service': service_name,
                        'Endpoint': endpoint_url,
                        'Status': status,
                        'HTTP Code': response.status_code,
                        'Response Time': f"{response.elapsed.total_seconds():.2f}s",
                        'Health': '🟢 HEALTHY' if status == 'UP' else '🔴 UNHEALTHY'
                    })
                except json.JSONDecodeError:
                    print(f"✗")
                    results.append({
                        'Service': service_name,
                        'Endpoint': endpoint_url,
                        'Status': 'INVALID_JSON',
                        'HTTP Code': response.status_code,
                        'Response Time': f"{response.elapsed.total_seconds():.2f}s",
                        'Health': '🟡 WARNING'
                    })
            else:
                print(f"✗")
                results.append({
                    'Service': service_name,
                    'Endpoint': endpoint_url,
                    'Status': f'HTTP_{response.status_code}',
                    'HTTP Code': response.status_code,
                    'Response Time': f"{response.elapsed.total_seconds():.2f}s",
                    'Health': '🔴 UNHEALTHY'
                })
                
        except requests.exceptions.Timeout:
            print(f"⏱")
            results.append({
                'Service': service_name,
                'Endpoint': endpoint_url,
                'Status': 'TIMEOUT',
                'HTTP Code': 'N/A',
                'Response Time': '>10s',
                'Health': '🔴 TIMEOUT'
            })
            
        except requests.exceptions.ConnectionError:
            print(f"🚫")
            results.append({
                'Service': service_name,
                'Endpoint': endpoint_url,
                'Status': 'CONNECTION_ERROR',
                'HTTP Code': 'N/A',
                'Response Time': 'N/A',
                'Health': '🔴 UNREACHABLE'
            })
            
        except Exception as e:
            print(f"💥")
            results.append({
                'Service': service_name,
                'Endpoint': endpoint_url,
                'Status': f'ERROR: {str(e)[:30]}',
                'HTTP Code': 'N/A',
                'Response Time': 'N/A',
                'Health': '🔴 ERROR'
            })
    
    return results

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch health check endpoints from Kubernetes services.")
    parser.add_argument("namespace", help="Kubernetes namespace to query")
    args = parser.parse_args()
    
    endpoints, services_without_health = get_health_check_endpoints(args.namespace)
    
    # Print services with health check endpoints
    if endpoints:
        print(f"\n✓ Found {len(endpoints)} valid health check endpoints in namespace '{args.namespace}':")
        print("-" * 70)
        for ep in endpoints:
            print(f"{ep['service']:<25} → {ep['endpoint']}")
        
        # Check health status of all endpoints
        health_results = check_health_status(endpoints)
        
        # Display results in tabular format
        print(f"\n📊 Health Check Results:")
        print("=" * 120)
        
        # Prepare table data
        table_data = []
        healthy_count = 0
        
        for result in health_results:
            table_data.append([
                result['Service'],
                result['Status'],
                result['HTTP Code'],
                result['Response Time'],
                result['Health']
            ])
            
            if result['Status'] == 'UP':
                healthy_count += 1
        
        # Print the table
        headers = ['Service Name', 'Status', 'HTTP Code', 'Response Time', 'Health']
        print(tabulate(table_data, headers=headers, tablefmt='grid', maxcolwidths=[20, 15, 10, 12, 15]))
        
        # Health summary
        total_endpoints = len(health_results)
        print(f"\n🏥 Health Summary:")
        print(f"   • Healthy Services: {healthy_count}/{total_endpoints}")
        print(f"   • Unhealthy Services: {total_endpoints - healthy_count}/{total_endpoints}")
        print(f"   • Success Rate: {(healthy_count/total_endpoints)*100:.1f}%")
        
    else:
        print(f"\n⚠ No valid health check endpoints found in namespace '{args.namespace}'")
    
    # Print services without health check endpoints
    if services_without_health:
        print(f"\n❌ Services without health check endpoints ({len(services_without_health)}):")
        print("-" * 70)
        for svc in services_without_health:
            print(f"  • {svc}")
    
    # Overall summary
    total_services = len(endpoints) + len(services_without_health)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n📋 Overall Summary ({timestamp}):")
    print(f"   • Total Services: {total_services}")
    print(f"   • Services with Health Endpoints: {len(endpoints)}")
    print(f"   • Services without Health Endpoints: {len(services_without_health)}")
    if endpoints:
        healthy_services = sum(1 for r in health_results if r['Status'] == 'UP')
        print(f"   • Currently Healthy: {healthy_services}")
        print(f"   • Currently Unhealthy: {len(endpoints) - healthy_services}")
