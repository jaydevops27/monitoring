#!/usr/bin/env python3
"""
Complete Kubernetes Health Checker
- Always checks pod health for all deployments
- Auto-discovers ingress URLs when available
- Provides detailed connection and HTTP error information
- Uses urllib3 with brotli encoding for faster requests
"""

import os
import sys
import time
import urllib3
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

# Disable urllib3 warnings for unverified HTTPS requests
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

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
                 max_workers: int = 20,
                 debug: bool = False):
        self.namespaces = namespaces or ["default"]
        self.health_paths = ["/health", "/healthz", "/health.html", "/ping", "/api/health", "/status"]
        self.timeout = timeout
        self.max_workers = max_workers
        self.debug = debug
        
        # Initialize urllib3 with connection pooling and brotli support
        self.http = urllib3.PoolManager(
            num_pools=10,
            maxsize=20,
            block=False,
            cert_reqs='CERT_NONE',  # Skip SSL verification
            ssl_show_warn=False
        )
        
        # Headers with brotli encoding support
        self.headers = {
            'Accept-Encoding': 'br, gzip, deflate',  # Brotli first, then gzip, then deflate
            'User-Agent': 'K8s-Health-Checker/1.0',
            'Accept': 'application/json, text/html, */*',
            'Connection': 'keep-alive'
        }
        
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
                                
                                # Build base URL - handle ingress paths properly
                                if rule.http and rule.http.paths:
                                    # For multiple paths, prefer root path or shortest path
                                    paths = rule.http.paths
                                    # Sort by path length, prefer root path
                                    sorted_paths = sorted(paths, key=lambda p: (len(p.path or "/"), p.path != "/"))
                                    best_path = sorted_paths[0]
                                    
                                    ingress_path = best_path.path or "/"
                                    # Clean up the path - remove trailing slashes except for root
                                    if ingress_path != "/" and ingress_path.endswith("/"):
                                        ingress_path = ingress_path.rstrip("/")
                                    
                                    # Build the base URL for the ingress
                                    if ingress_path == "/":
                                        url = f"{scheme}://{rule.host}"
                                    else:
                                        url = f"{scheme}://{rule.host}{ingress_path}"
                                else:
                                    # No specific paths, use host root
                                    url = f"{scheme}://{rule.host}"
                                
                                if self.debug:
                                    print(f"   🔗 Found ingress URL for {app_name}: {url}")
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

    def check_health_endpoint(self, base_url: str) -> Tuple[str, Optional[float], Optional[str]]:
        """Check health endpoint using urllib3 with brotli encoding"""
        start_time = time.time()
        
        if self.debug:
            print(f"   🔍 Testing health endpoints for: {base_url}")
        
        # Try health-specific paths first
        for path in self.health_paths:
            try:
                # Properly construct URL
                if base_url.endswith('/') and path.startswith('/'):
                    test_url = base_url + path[1:]  # Remove leading slash from path
                elif not base_url.endswith('/') and not path.startswith('/'):
                    test_url = base_url + '/' + path  # Add slash between
                else:
                    test_url = base_url + path  # One already has proper slash
                
                if self.debug:
                    print(f"   🧪 Trying: {test_url}")
                
                # Make request with urllib3 and brotli encoding
                response = self.http.request(
                    'GET', 
                    test_url, 
                    headers=self.headers,
                    timeout=self.timeout,
                    retries=urllib3.Retry(total=1, connect=1, read=1, status=1)
                )
                
                response_time = round((time.time() - start_time) * 1000, 2)
                
                if self.debug:
                    encoding = response.headers.get('Content-Encoding', 'none')
                    print(f"   📊 Response: {response.status}, Encoding: {encoding}, Size: {len(response.data)} bytes")
                
                if response.status == 200:
                    if self.debug:
                        print(f"   ✅ SUCCESS: {test_url} returned 200")
                    return "UP", response_time, f"Health endpoint: {path}"
                elif response.status == 404:
                    if self.debug:
                        print(f"   ❌ 404: {test_url}")
                    continue  # Try next path
                else:
                    if self.debug:
                        print(f"   ⚠️  {response.status}: {test_url}")
                    return f"HTTP {response.status}", response_time, f"Health endpoint {path} returned {response.status}"
                    
            except urllib3.exceptions.ConnectTimeoutError:
                if self.debug:
                    print(f"   ⏰ Connect timeout: {test_url}")
                return "Connect Timeout", self.timeout * 1000, f"Connection timeout after {self.timeout}s"
                
            except urllib3.exceptions.ReadTimeoutError:
                if self.debug:
                    print(f"   ⏰ Read timeout: {test_url}")
                return "Read Timeout", self.timeout * 1000, f"Read timeout after {self.timeout}s"
                
            except urllib3.exceptions.NewConnectionError as e:
                if self.debug:
                    print(f"   ❌ Connection failed: {test_url} - {str(e)[:100]}")
                if "Name or service not known" in str(e) or "nodename nor servname provided" in str(e):
                    return "DNS Failed", None, f"DNS resolution failed for {test_url}"
                elif "Connection refused" in str(e):
                    return "Connection Refused", None, f"Connection refused to {test_url}"
                else:
                    continue  # Try next path
                    
            except urllib3.exceptions.SSLError as e:
                if self.debug:
                    print(f"   🔒 SSL Error: {test_url} - {str(e)[:100]}")
                return "SSL Error", None, f"SSL certificate error: {str(e)}"
                
            except urllib3.exceptions.MaxRetryError as e:
                if self.debug:
                    print(f"   🔄 Max retry error: {test_url} - {str(e)[:100]}")
                if "Name or service not known" in str(e):
                    return "DNS Failed", None, f"DNS resolution failed for {test_url}"
                elif "Connection refused" in str(e):
                    return "Connection Refused", None, f"Connection refused to {test_url}"
                else:
                    continue  # Try next path
                    
            except Exception as e:
                if self.debug:
                    print(f"   ❓ Other error: {test_url} - {str(e)[:100]}")
                continue  # Try next path
        
        # If no health endpoints work, try base URL
        if self.debug:
            print(f"   🧪 Trying base URL: {base_url}")
        try:
            response = self.http.request(
                'GET', 
                base_url, 
                headers=self.headers,
                timeout=self.timeout,
                retries=urllib3.Retry(total=1, connect=1, read=1, status=1)
            )
            
            response_time = round((time.time() - start_time) * 1000, 2)
            
            if self.debug:
                encoding = response.headers.get('Content-Encoding', 'none')
                print(f"   📊 Base URL response: {response.status}, Encoding: {encoding}, Size: {len(response.data)} bytes")
            
            if response.status == 200:
                if self.debug:
                    print(f"   ✅ Base URL works: {base_url}")
                return "UP (Base)", response_time, "No health endpoint, but base URL works"
            elif response.status == 404:
                if self.debug:
                    print(f"   ❌ Base URL 404: {base_url}")
                return "HTTP 404", response_time, "Base URL returns 404 Not Found"
            elif response.status == 503:
                if self.debug:
                    print(f"   ⚠️  Base URL 503: {base_url}")
                return "HTTP 503", response_time, "Service Unavailable - app may be down"
            elif response.status == 502:
                if self.debug:
                    print(f"   ⚠️  Base URL 502: {base_url}")
                return "HTTP 502", response_time, "Bad Gateway - upstream service issue"
            elif response.status == 500:
                if self.debug:
                    print(f"   ⚠️  Base URL 500: {base_url}")
                return "HTTP 500", response_time, "Internal Server Error"
            else:
                if self.debug:
                    print(f"   ⚠️  Base URL {response.status}: {base_url}")
                return f"HTTP {response.status}", response_time, f"Base URL returned {response.status}"
                
        except urllib3.exceptions.ConnectTimeoutError:
            if self.debug:
                print(f"   ⏰ Base URL connect timeout: {base_url}")
            return "Connect Timeout", self.timeout * 1000, f"Connection timeout after {self.timeout}s"
            
        except urllib3.exceptions.ReadTimeoutError:
            if self.debug:
                print(f"   ⏰ Base URL read timeout: {base_url}")
            return "Read Timeout", self.timeout * 1000, f"Read timeout after {self.timeout}s"
            
        except urllib3.exceptions.NewConnectionError as e:
            if self.debug:
                print(f"   ❌ Base URL connection failed: {base_url}")
            if "Name or service not known" in str(e):
                return "DNS Failed", None, f"DNS resolution failed for {base_url}"
            elif "Connection refused" in str(e):
                return "Connection Refused", None, f"Connection refused to {base_url}"
            else:
                return "Connection Failed", None, f"Cannot connect to {base_url}: {str(e)}"
                
        except urllib3.exceptions.SSLError as e:
            if self.debug:
                print(f"   🔒 Base URL SSL error: {base_url}")
            return "SSL Error", None, f"SSL certificate error: {str(e)}"
            
        except urllib3.exceptions.MaxRetryError as e:
            if self.debug:
                print(f"   🔄 Base URL max retry error: {base_url}")
            if "Name or service not known" in str(e):
                return "DNS Failed", None, f"DNS resolution failed for {base_url}"
            elif "Connection refused" in str(e):
                return "Connection Refused", None, f"Connection refused to {base_url}"
            else:
                return "Connection Failed", None, f"Cannot connect to {base_url}: {str(e)}"
                
        except Exception as e:
            if self.debug:
                print(f"   ❓ Base URL other error: {base_url}")
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

    def cleanup(self):
        """Clean up urllib3 connection pools"""
        if hasattr(self, 'http'):
            self.http.clear()

def main():
    parser = argparse.ArgumentParser(description="Complete Kubernetes Health Checker with urllib3 + Brotli")
    parser.add_argument("-n", "--namespaces", nargs="+", default=["default"],
                       help="Kubernetes namespaces to check (use 'all' for all namespaces)")
    parser.add_argument("-w", "--watch", action="store_true", help="Watch mode - continuously monitor")
    parser.add_argument("-i", "--interval", type=int, default=60, help="Watch interval in seconds")
    parser.add_argument("--timeout", type=int, default=10, help="HTTP request timeout in seconds")
    parser.add_argument("--max-workers", type=int, default=20, help="Max concurrent health checks")
    parser.add_argument("--debug", action="store_true", help="Enable debug output for URL testing and compression details")
    
    args = parser.parse_args()
    
    checker = CompleteHealthChecker(
        namespaces=args.namespaces,
        timeout=args.timeout,
        max_workers=args.max_workers,
        debug=args.debug
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
        finally:
            checker.cleanup()
    else:
        try:
            results = checker.check_all_apps()
            checker.print_results(results)
        finally:
            checker.cleanup()

if __name__ == "__main__":
    main()
