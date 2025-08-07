import argparse
import logging
from kubernetes import client, config
import urllib3
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
    
    # Get all ingresses once to avoid repeated API calls
    ingresses = networking_v1.list_namespaced_ingress(namespace)
    
    for svc in services.items:
        svc_name = svc.metadata.name
        selector = svc.spec.selector
        if not selector:
            continue
            
        # Find one pod matching the service selector
        matched_pod = None
        for pod in pods.items:
            pod_labels = pod.metadata.labels or {}
            if all(pod_labels.get(k) == v for k, v in selector.items()):
                matched_pod = pod
                break
                
        if not matched_pod:
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
                                        break
                                if svc_name in health_endpoints:
                                    break
                        if svc_name in health_endpoints:
                            break
    
    return list(health_endpoints.values())

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch health check endpoints from Kubernetes services.")
    parser.add_argument("namespace", help="Kubernetes namespace to query")
    args = parser.parse_args()
    
    endpoints = get_health_check_endpoints(args.namespace)
    
    # Print clean summary
    if endpoints:
        print(f"\n✓ Found {len(endpoints)} valid health check endpoints in namespace '{args.namespace}':")
        print("-" * 60)
        for ep in endpoints:
            print(f"{ep['service']:<25} → {ep['endpoint']}")
    else:
        print(f"\n⚠ No valid health check endpoints found in namespace '{args.namespace}'")
