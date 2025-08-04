#!/usr/bin/env python3
"""
Actuator Health Check Monitor
Monitors multiple DNS endpoints for health status and reports UP/DOWN status
"""

import requests
import concurrent.futures
import logging
import time
import json
import argparse
from datetime import datetime
from typing import List, Dict, Tuple
from urllib.parse import urlparse
import csv
import os

class HealthCheckMonitor:
    def __init__(self, config: Dict):
        self.config = config
        self.setup_logging()
        
    def setup_logging(self):
        """Setup logging configuration"""
        log_level = getattr(logging, self.config.get('log_level', 'INFO').upper())
        logging.basicConfig(
            level=log_level,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(self.config.get('log_file', 'health_monitor.log')),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)

    def load_endpoints_from_file(self, file_path: str) -> List[str]:
        """Load DNS endpoints from text file"""
        endpoints = []
        try:
            with open(file_path, 'r') as file:
                for line in file:
                    endpoint = line.strip()
                    if endpoint and not endpoint.startswith('#'):  # Skip empty lines and comments
                        # Ensure endpoint has proper protocol
                        if not endpoint.startswith(('http://', 'https://')):
                            endpoint = f"https://{endpoint}"
                        endpoints.append(endpoint)
            
            self.logger.info(f"Loaded {len(endpoints)} endpoints from {file_path}")
            return endpoints
            
        except FileNotFoundError:
            self.logger.error(f"File {file_path} not found")
            return []
        except Exception as e:
            self.logger.error(f"Error loading endpoints: {str(e)}")
            return []

    def check_single_endpoint(self, endpoint: str) -> Tuple[str, str, float, str]:
        """
        Check a single endpoint health status
        Returns: (endpoint, status, response_time, error_message)
        """
        start_time = time.time()
        
        try:
            # Make HTTP request with timeout
            response = requests.get(
                endpoint,
                timeout=self.config.get('timeout', 10),
                headers={'User-Agent': 'HealthCheckMonitor/1.0'},
                verify=self.config.get('verify_ssl', True)
            )
            
            response_time = time.time() - start_time
            
            # Check if response indicates success
            if response.status_code == 200:
                # Check response content for success indicators
                content = response.text.lower()
                success_indicators = self.config.get('success_indicators', ['success', 'up', 'healthy', 'ok'])
                
                if any(indicator in content for indicator in success_indicators):
                    return endpoint, "UP", response_time, ""
                else:
                    return endpoint, "DOWN", response_time, f"Success indicator not found in response"
            else:
                return endpoint, "DOWN", response_time, f"HTTP {response.status_code}"
                
        except requests.exceptions.Timeout:
            response_time = time.time() - start_time
            return endpoint, "DOWN", response_time, "Timeout"
        except requests.exceptions.ConnectionError:
            response_time = time.time() - start_time
            return endpoint, "DOWN", response_time, "Connection Error"
        except Exception as e:
            response_time = time.time() - start_time
            return endpoint, "DOWN", response_time, str(e)

    def check_endpoints_concurrent(self, endpoints: List[str]) -> List[Tuple[str, str, float, str]]:
        """Check multiple endpoints concurrently"""
        results = []
        max_workers = self.config.get('max_workers', 20)
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all tasks
            future_to_endpoint = {
                executor.submit(self.check_single_endpoint, endpoint): endpoint 
                for endpoint in endpoints
            }
            
            # Collect results as they complete
            for future in concurrent.futures.as_completed(future_to_endpoint):
                try:
                    result = future.result()
                    results.append(result)
                except Exception as e:
                    endpoint = future_to_endpoint[future]
                    self.logger.error(f"Error checking {endpoint}: {str(e)}")
                    results.append((endpoint, "DOWN", 0.0, str(e)))
        
        return results

    def generate_report(self, results: List[Tuple[str, str, float, str]]) -> Dict:
        """Generate summary report from results"""
        total_endpoints = len(results)
        up_count = sum(1 for _, status, _, _ in results if status == "UP")
        down_count = total_endpoints - up_count
        
        avg_response_time = sum(response_time for _, _, response_time, _ in results) / total_endpoints if total_endpoints > 0 else 0
        
        report = {
            'timestamp': datetime.now().isoformat(),
            'total_endpoints': total_endpoints,
            'up_count': up_count,
            'down_count': down_count,
            'availability_percentage': (up_count / total_endpoints * 100) if total_endpoints > 0 else 0,
            'average_response_time': round(avg_response_time, 3),
            'results': results
        }
        
        return report

    def save_results_to_csv(self, results: List[Tuple[str, str, float, str]], filename: str):
        """Save results to CSV file"""
        try:
            with open(filename, 'w', newline='') as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(['Endpoint', 'Status', 'Response Time (s)', 'Error Message', 'Timestamp'])
                
                timestamp = datetime.now().isoformat()
                for endpoint, status, response_time, error in results:
                    writer.writerow([endpoint, status, round(response_time, 3), error, timestamp])
            
            self.logger.info(f"Results saved to {filename}")
        except Exception as e:
            self.logger.error(f"Error saving CSV: {str(e)}")

    def save_results_to_json(self, report: Dict, filename: str):
        """Save report to JSON file"""
        try:
            with open(filename, 'w') as jsonfile:
                json.dump(report, jsonfile, indent=2)
            
            self.logger.info(f"Report saved to {filename}")
        except Exception as e:
            self.logger.error(f"Error saving JSON: {str(e)}")

    def print_summary(self, report: Dict):
        """Print summary to console"""
        print("\n" + "="*60)
        print("HEALTH CHECK MONITOR SUMMARY")
        print("="*60)
        print(f"Timestamp: {report['timestamp']}")
        print(f"Total Endpoints: {report['total_endpoints']}")
        print(f"UP: {report['up_count']} ({report['availability_percentage']:.2f}%)")
        print(f"DOWN: {report['down_count']}")
        print(f"Average Response Time: {report['average_response_time']:.3f}s")
        print("="*60)
        
        # Show DOWN endpoints
        down_endpoints = [(endpoint, error) for endpoint, status, _, error in report['results'] if status == "DOWN"]
        if down_endpoints:
            print(f"\nDOWN ENDPOINTS ({len(down_endpoints)}):")
            print("-" * 60)
            for endpoint, error in down_endpoints:
                print(f"❌ {endpoint}")
                if error:
                    print(f"   Error: {error}")
        
        # Show slowest endpoints
        slowest = sorted(report['results'], key=lambda x: x[2], reverse=True)[:5]
        if slowest:
            print(f"\nSLOWEST ENDPOINTS (Top 5):")
            print("-" * 60)
            for endpoint, status, response_time, _ in slowest:
                status_icon = "✅" if status == "UP" else "❌"
                print(f"{status_icon} {endpoint} - {response_time:.3f}s")

    def run_monitoring(self, endpoints_file: str):
        """Run the monitoring process"""
        self.logger.info("Starting health check monitoring")
        
        # Load endpoints
        endpoints = self.load_endpoints_from_file(endpoints_file)
        if not endpoints:
            self.logger.error("No endpoints to monitor")
            return
        
        # Check endpoints
        self.logger.info(f"Checking {len(endpoints)} endpoints...")
        results = self.check_endpoints_concurrent(endpoints)
        
        # Generate report
        report = self.generate_report(results)
        
        # Save results
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if self.config.get('save_csv', True):
            self.save_results_to_csv(results, f"health_check_{timestamp}.csv")
        
        if self.config.get('save_json', True):
            self.save_results_to_json(report, f"health_report_{timestamp}.json")
        
        # Print summary
        self.print_summary(report)
        
        self.logger.info("Health check monitoring completed")
        return report


def load_config(config_file: str = None) -> Dict:
    """Load configuration from file or use defaults"""
    default_config = {
        'timeout': 10,
        'max_workers': 20,
        'success_indicators': ['success', 'up', 'healthy', 'ok', '"status":"UP"'],
        'verify_ssl': True,
        'log_level': 'INFO',
        'log_file': 'health_monitor.log',
        'save_csv': True,
        'save_json': True
    }
    
    if config_file and os.path.exists(config_file):
        try:
            with open(config_file, 'r') as f:
                file_config = json.load(f)
            default_config.update(file_config)
        except Exception as e:
            print(f"Error loading config file: {e}")
    
    return default_config


def create_sample_endpoints_file():
    """Create a sample endpoints file for testing"""
    sample_endpoints = [
        "# Sample health check endpoints",
        "https://httpbin.org/status/200",
        "https://jsonplaceholder.typicode.com/posts/1",
        "https://api.github.com/users/octocat",
        "# Add your actual endpoints below:",
        "# your-service-1.com/actuator/health",
        "# your-service-2.com/health",
    ]
    
    with open('sample_endpoints.txt', 'w') as f:
        f.write('\n'.join(sample_endpoints))
    
    print("Created sample_endpoints.txt - please update with your actual endpoints")


def main():
    parser = argparse.ArgumentParser(description='Health Check Monitor for Actuator Endpoints')
    parser.add_argument('endpoints_file', nargs='?', default='endpoints.txt',
                        help='Text file containing DNS endpoints (default: endpoints.txt)')
    parser.add_argument('--config', '-c', help='Configuration file (JSON format)')
    parser.add_argument('--create-sample', action='store_true',
                        help='Create a sample endpoints file')
    parser.add_argument('--continuous', '-C', type=int, metavar='INTERVAL',
                        help='Run continuously with specified interval in seconds')
    
    args = parser.parse_args()
    
    if args.create_sample:
        create_sample_endpoints_file()
        return
    
    # Load configuration
    config = load_config(args.config)
    
    # Create monitor instance
    monitor = HealthCheckMonitor(config)
    
    if args.continuous:
        print(f"Running continuous monitoring every {args.continuous} seconds. Press Ctrl+C to stop.")
        try:
            while True:
                monitor.run_monitoring(args.endpoints_file)
                print(f"\nWaiting {args.continuous} seconds for next check...")
                time.sleep(args.continuous)
        except KeyboardInterrupt:
            print("\nMonitoring stopped by user")
    else:
        # Run once
        monitor.run_monitoring(args.endpoints_file)


if __name__ == "__main__":
    main()
