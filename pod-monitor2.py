#!/usr/bin/env python3
import os
import sys
import time
import requests
import argparse
import concurrent.futures
from datetime import datetime
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass

try:
    from kubernetes import client, config
    from kubernetes.client.rest import ApiException
except ImportError:
    print("❌ Error: kubernetes library not found. Install with: pip install kubernetes")
    sys.exit(1)

@dataclass
class AppHealth:
    """Complete health status for an application"""
    name: str
    namespace: str
    pod_status: str
    ready_pods: int
    total_pods: int
    has_ingress: bool = False
    url: Optional[str] = None
    http_status: Optional[str] = None
    response_time: Optional[float] = None
    ingress_class: Optional[str] = None
    error_details: Optional[str] = None

class CompleteHealthChecker:
    def __init__(self, 
                 namespaces: List[str] = None,
                 timeout: int = 10,
                 max_workers: int = 20):
        self.namespaces = namespaces or ["default"]
        self.health_paths = ["/health", "/healthz", "/health.html", "/ping", "/api/health", "/status"]
        self.timeout = timeout
        self.max_workers = max_workers
        
        # Initialize Kubernetes client
        try:
            try:
                config.load_incluster_config()
                print("🔧 Using in-cluster Kubernetes configuration")
            except:
                config.load_kube_config()
                print("🔧 Using local Kubernetes configuration")
                
            self.v1 = client.CoreV1Api()
            self.apps_v1 = client.AppsV1Api()
            self.networking_v1 = client.NetworkingV1Api()
        except Exception as e:
            print(f"❌ Failed to initialize Kubernetes client: {e}")
            sys.exit(1)

    def get_all_deployments(self) -> Dict[str, List[str]]:
        """Get ALL deployments across namespaces"""
        all_deployments = {}
        
        for namespace in self.namespaces:
            try:
                if namespace == "all":
                    ns_list = self.v1.list_namespace()
                    target_namespaces = [ns.metadata.name for ns in ns_list.items 
                                       if not ns.metadata.name.startswith('kube-')]
                else:
                    target_namespaces = [namespace]
                
                for ns in target_namespaces:
                    deployments = self.apps_v1.list_namespaced_deployment(namespace=ns)
                    deployment_names = [dep.metadata.name for dep in deployments.items]
                    if deployment_names:
                        all_deployments[ns] = deployment_names
                        
            except ApiException as e:
                print(f"❌ Error getting deployments from namespace {namespace}: {e}")
        
        return all_deployments

    def get_pod_status(self, namespace: str, app_name: str) -> Tuple[str, int, int]:
        """Get detailed pod status for an app"""
        try:
            label_selectors = [
                f"app={app_name}",
                f"app.kubernetes.io/name={app_name}",
                f"k8s-app={app_name}"
            ]
            
            pods = None
            for selector in label_selectors:
                pods = self.v1.list_namespaced_pod(namespace=namespace, label_selector=selector)
                if pods.items:
                    break
            
            if not pods or not pods.items:
                return "No Pods", 0, 0
            
            total_pods = len(pods.items)
            ready_pods = 0
            running_pods = 0
            
            for pod in pods.items:
                # Check if pod is running
                if pod.status.phase == "Running":
                    running_pods += 1
                
                # Check if pod is ready
                if pod.status.conditions:
                    for condition in pod.status.conditions:
                        if condition.type == "Ready" and condition.status == "True":
                            ready_pods += 1
                            break
            
            # Determine overall status
            if ready_pods == total_pods and total_pods > 0:
                return "Healthy", ready_pods, total_pods
            elif ready_pods > 0:
                return "Partial", ready_pods, total_pods
            elif running_pods > 0:
                return "Starting", ready_pods, total_pods
            else:
                return "Unhealthy", ready_pods, total_pods
                
        except ApiException as e:
            return f"K8s Error", 0, 0

    def find_ingress_for_app(self, namespace: str, app_name: str) -> Optional[Tuple[str, str]]:
        """Find ingress URL for an app. Returns (url, ingress_class) or None"""
        try:
            ingresses = self.networking_v1.list_namespaced_ingress(namespace=namespace)
            
            for ingress in ingresses.items:
                # Check if this ingress relates to our app
                if self.ingress_matches_app(ingress, app_name):
                    # Get ingress class
                    ingress_class = "unknown"
                    if ingress.spec.ingress_class_name:
                        ingress_class = ingress.spec.ingress_class_name
                    elif ingress.metadata.annotations:
                        ingress_class = ingress.metadata.annotations.get(
                            'kubernetes.io/ingress.class', 
                            ingress.metadata.annotations.get('nginx.ingress.kubernetes.io/ingress.class', 'unknown')
                        )
                    
                    # Extract URL
                    if ingress.spec.rules:
                        for rule in ingress.spec.rules:
                            if rule.host:
                                # Check for TLS
                                tls_enabled = False
                                if ingress.spec.tls:
                                    for tls in ingress.spec.tls:
                                        if rule.host in (tls.hosts or []):
                                            tls_enabled = True
                                            break
                                
                                scheme = "https" if tls_enabled else "http"
                                
                                # Build URL
                                if rule.http and rule.http.paths:
                                    path = rule.http.paths[0].path or "/"
                                    url = f"{scheme}://{rule.host}{path}".rstrip('/')
                                else:
                                    url = f"{scheme}://{rule.host}"
                                
                                return url, ingress_class
                                
        except ApiException as e:
            print(f"   ⚠️  Could not check ingress for {app_name}: {e}")
        
        return None

    def ingress_matches_app(self, ingress, app_name: str) -> bool:
        """Check if an ingress is related to the app"""
        ingress_name = ingress.metadata.name.lower()
        app_name_lower = app_name.lower()
        
        # Direct name match
        if app_name_lower in ingress_name or ingress_name in app_name_lower:
            return True
        
        # Check backend services
        if ingress.spec.rules:
            for rule in ingress.spec.rules:
                if rule.http and rule.http.paths:
                    for path in rule.http.paths:
                        if path.backend and path.backend.service:
                            service_name = path.backend.service.name.lower()
                            if app_name_lower in service_name or service_name in app_name_lower:
                                return True
        
        # Check labels
        if ingress.metadata.labels:
            app_label = ingress.metadata.labels.get('app', '').lower()
            if app_label == app_name_lower:
                return True
        
        return False

    def check_health_endpoint(self, url: str) -> Tuple[str, Optional[float], Optional[str]]:
        """Check health endpoint and return (status, response_time, error_details)"""
        start_time = time.time()
        
        # Try health-specific paths first
        for path in self.health_paths:
            try:
                test_url = f"{url}{path}".replace("//", "/").replace(":/", "://")
                response = requests.get(test_url, timeout=self.timeout, verify=False)
                response_time = round((time.time() - start_time) * 1000, 2)
                
                if response.status_code == 200:
                    return "UP", response_time, f"Health endpoint: {path}"
                elif response.status_code == 404:
                    continue  # Try next path
                else:
                    return f"HTTP {response.status_code}", response_time, f"Health endpoint {path} returned {response.status_code}"
                    
            except requests.exceptions.ConnectionError as e:
                error_detail = f"Connection failed to {test_url}: {str(e)}"
                if "Name or service not known" in str(e) or "nodename nor servname provided" in str(e):
                    return "DNS Failed", None, f"DNS resolution failed for {test_url}"
                elif "Connection refused" in str(e):
                    return "Connection Refused", None, f"Connection refused to {test_url}"
                else:
                    continue  # Try next path
                    
            except requests.exceptions.Timeout:
                return "Timeout", self.timeout * 1000, f"Timeout after {self.timeout}s trying {test_url}"
            except requests.exceptions.SSLError as e:
                return "SSL Error", None, f"SSL certificate error: {str(e)}"
            except Exception as e:
                continue  # Try next path
        
        # If no health endpoints work, try base URL
        try:
            response = requests.get(url, timeout=self.timeout, verify=False)
            response_time = round((time.time() - start_time) * 1000, 2)
            
            if response.status_code == 200:
                return "UP (Base)", response_time, "No health endpoint, but base URL works"
            elif response.status_code == 404:
                return "HTTP 404", response_time, "Base URL returns 404 Not Found"
            elif response.status_code == 503:
                return "HTTP 503", response_time, "Service Unavailable - app may be down"
            elif response.status_code == 502:
                return "HTTP 502", response_time, "Bad Gateway - upstream service issue"
            elif response.status_code == 500:
                return "HTTP 500", response_time, "Internal Server Error"
            else:
                return f"HTTP {response.status_code}", response_time, f"Base URL returned {response.status_code}"
                
        except requests.exceptions.ConnectionError as e:
            if "Name or service not known" in str(e):
                return "DNS Failed", None, f"DNS resolution failed for {url}"
            elif "Connection refused" in str(e):
                return "Connection Refused", None, f"Connection refused to {url}"
            else:
                return "Connection Failed", None, f"Cannot connect to {url}: {str(e)}"
        except requests.exceptions.Timeout:
            return "Timeout", self.timeout * 1000, f"Request timeout after {self.timeout}s"
        except requests.exceptions.SSLError as e:
            return "SSL Error", None, f"SSL certificate error: {str(e)}"
        except Exception as e:
            return "Request Failed", None, f"HTTP request failed: {str(e)}"

    def check_app_health(self, namespace: str, app_name: str) -> AppHealth:
        """Check complete health for a single app"""
        # Always check pod status
        pod_status, ready_pods, total_pods = self.get_pod_status(namespace, app_name)
        
        # Try to find ingress
        ingress_info = self.find_ingress_for_app(namespace, app_name)
        
        if ingress_info:
            url, ingress_class = ingress_info
            http_status, response_time, error_details = self.check_health_endpoint(url)
            
            return AppHealth(
                name=app_name,
                namespace=namespace,
                pod_status=pod_status,
                ready_pods=ready_pods,
                total_pods=total_pods,
                has_ingress=True,
                url=url,
                http_status=http_status,
                response_time=response_time,
                ingress_class=ingress_class,
                error_details=error_details
            )
        else:
            # No ingress found, but still report pod status
            return AppHealth(
                name=app_name,
                namespace=namespace,
                pod_status=pod_status,
                ready_pods=ready_pods,
                total_pods=total_pods,
                has_ingress=False,
                url="No Ingress",
                error_details="No ingress resource found for this app"
            )

    def check_all_apps(self) -> List[AppHealth]:
        """Check health of ALL apps (with and without ingress)"""
        print(f"🔍 Discovering ALL applications in namespaces: {self.namespaces}")
        
        all_deployments = self.get_all_deployments()
        if not all_deployments:
            print("❌ No deployments found")
            return []
        
        total_apps = sum(len(apps) for apps in all_deployments.values())
        apps_with_ingress = 0
        
        print(f"📊 Found {total_apps} total applications across {len(all_deployments)} namespaces")
        print("🚀 Checking pod health and ingress discovery...")
        print("=" * 120)
        
        results = []
        
        # Prepare tasks for parallel execution
        tasks = []
        for namespace, apps in all_deployments.items():
            for app in apps:
                tasks.append((namespace, app))
        
        # Execute health checks in parallel
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_app = {
                executor.submit(self.check_app_health, namespace, app): (namespace, app) 
                for namespace, app in tasks
            }
            
            for future in concurrent.futures.as_completed(future_to_app):
                namespace, app = future_to_app[future]
                try:
                    result = future.result()
                    results.append(result)
                    
                    if result.has_ingress:
                        apps_with_ingress += 1
                        status_icon = "🌐" if result.http_status and result.http_status.startswith("UP") else "⚠️"
                        print(f"{status_icon} {namespace}/{app} - Pods: {result.pod_status}, HTTP: {result.http_status}")
                    else:
                        print(f"📦 {namespace}/{app} - Pods: {result.pod_status}, No ingress")
                        
                except Exception as e:
                    print(f"✗ Error checking {namespace}/{app}: {e}")
        
        print(f"\n📈 Discovery complete: {apps_with_ingress}/{total_apps} apps have ingress")
        return results

    def print_results(self, results: List[AppHealth]):
        """Print comprehensive results"""
        print("\n" + "=" * 130)
        print(f"📊 COMPLETE HEALTH CHECK SUMMARY - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 130)
        
        if not results:
            print("❌ No applications found")
            return
        
        # Separate apps with and without ingress
        with_ingress = [r for r in results if r.has_ingress]
        without_ingress = [r for r in results if not r.has_ingress]
        
        # Print apps with ingress
        if with_ingress:
            print(f"\n🌐 APPS WITH INGRESS ({len(with_ingress)} apps)")
            print("-" * 130)
            print(f"{'App':<20} {'Namespace':<12} {'Pods':<8} {'HTTP Status':<15} {'Time(ms)':<10} {'URL':<40} {'Details':<25}")
            print("-" * 130)
            
            for result in with_ingress:
                # Choose emoji
                if result.pod_status == "Healthy" and result.http_status and result.http_status.startswith("UP"):
                    emoji = "✅"
                elif result.pod_status in ["Healthy", "Partial"] or (result.http_status and result.http_status.startswith("UP")):
                    emoji = "⚠️"
                else:
                    emoji = "❌"
                
                pods = f"{result.ready_pods}/{result.total_pods}"
                http_status = result.http_status or "N/A"
                response_time = f"{result.response_time}" if result.response_time else "N/A"
                url_short = result.url[:37] + "..." if len(result.url) > 40 else result.url
                details = result.error_details[:22] + "..." if result.error_details and len(result.error_details) > 25 else result.error_details or ""
                
                print(f"{emoji} {result.name:<18} {result.namespace:<12} {pods:<8} {http_status:<15} {response_time:<10} {url_short:<40} {details}")
        
        # Print apps without ingress
        if without_ingress:
            print(f"\n📦 APPS WITHOUT INGRESS ({len(without_ingress)} apps)")
            print("-" * 80)
            print(f"{'App':<25} {'Namespace':<15} {'Pod Status':<12} {'Pods':<8} {'Notes':<20}")
            print("-" * 80)
            
            for result in without_ingress:
                if result.pod_status == "Healthy":
                    emoji = "✅"
                elif result.pod_status in ["Partial", "Starting"]:
                    emoji = "⚠️"
                else:
                    emoji = "❌"
                
                pods = f"{result.ready_pods}/{result.total_pods}"
                notes = "Internal service only" if result.pod_status == "Healthy" else "Check pod logs"
                
                print(f"{emoji} {result.name:<23} {result.namespace:<15} {result.pod_status:<12} {pods:<8} {notes}")
        
        # Summary statistics
        total_apps = len(results)
        healthy_with_ingress = sum(1 for r in with_ingress if r.pod_status == "Healthy" and r.http_status and r.http_status.startswith("UP"))
        healthy_without_ingress = sum(1 for r in without_ingress if r.pod_status == "Healthy")
        total_healthy = healthy_with_ingress + healthy_without_ingress
        
        print("\n" + "=" * 130)
        print(f"📈 SUMMARY:")
        print(f"   Total apps: {total_apps}")
        print(f"   Apps with ingress: {len(with_ingress)} ({healthy_with_ingress} healthy)")
        print(f"   Apps without ingress: {len(without_ingress)} ({healthy_without_ingress} healthy)")
        print(f"   Overall health: {total_healthy}/{total_apps} apps healthy")
        
        # Ingress class summary
        if with_ingress:
            ingress_classes = {}
            for r in with_ingress:
                if r.ingress_class and r.ingress_class != "unknown":
                    ingress_classes[r.ingress_class] = ingress_classes.get(r.ingress_class, 0) + 1
            if ingress_classes:
                print(f"   Ingress classes: {dict(ingress_classes)}")
        
        if total_healthy == total_apps:
            print("🎉 All applications are healthy!")
        elif total_healthy > 0:
            print("⚠️  Some applications need attention")
        else:
            print("🚨 Critical: No applications are fully healthy")

def main():
    parser = argparse.ArgumentParser(description="Complete Kubernetes Health Checker")
    parser.add_argument("-n", "--namespaces", nargs="+", default=["default"],
                       help="Kubernetes namespaces to check (use 'all' for all namespaces)")
    parser.add_argument("-w", "--watch", action="store_true", help="Watch mode - continuously monitor")
    parser.add_argument("-i", "--interval", type=int, default=60, help="Watch interval in seconds")
    parser.add_argument("--timeout", type=int, default=10, help="HTTP request timeout in seconds")
    parser.add_argument("--max-workers", type=int, default=20, help="Max concurrent health checks")
    
    args = parser.parse_args()
    
    checker = CompleteHealthChecker(
        namespaces=args.namespaces,
        timeout=args.timeout,
        max_workers=args.max_workers
    )
    
    if args.watch:
        print(f"👀 Starting continuous health monitoring (interval: {args.interval}s)")
        print("Press Ctrl+C to stop")
        
        try:
            while True:
                results = checker.check_all_apps()
                checker.print_results(results)
                print(f"\n⏰ Next check in {args.interval} seconds...")
                time.sleep(args.interval)
                os.system('clear' if os.name == 'posix' else 'cls')
        except KeyboardInterrupt:
            print("\n👋 Health monitoring stopped")
    else:
        results = checker.check_all_apps()
        checker.print_results(results)

if __name__ == "__main__":
    main()
