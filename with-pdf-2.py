import argparse
from kubernetes import client, config
import urllib3
import requests
import json
from tabulate import tabulate
from datetime import datetime
import os
from pathlib import Path
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.platypus.tableofcontents import TableOfContents
import sys
from io import StringIO

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ANSI colors for terminal output
class C:
    G = '\033[92m'  # Green
    Y = '\033[93m'  # Yellow  
    R = '\033[91m'  # Red
    C = '\033[96m'  # Cyan
    B = '\033[1m'   # Bold
    E = '\033[0m'   # End

class HealthCheckReport:
    def __init__(self, namespace, output_dir="reports"):
        self.namespace = namespace
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.timestamp = datetime.now()
        self.report_data = {
            'namespace': namespace,
            'timestamp': self.timestamp,
            'health_results': [],
            'basic_results': [],
            'statistics': {},
            'issues': [],
            'service_categories': {},
            'summary': ''
        }
        
    def generate_pdf(self, filename=None):
        """Generate PDF report"""
        if not filename:
            filename = f"k8s_health_report_{self.namespace}_{self.timestamp.strftime('%Y%m%d_%H%M%S')}.pdf"
        
        filepath = self.output_dir / filename
        doc = SimpleDocTemplate(str(filepath), pagesize=A4, leftMargin=0.5*inch, rightMargin=0.5*inch)
        story = []
        styles = getSampleStyleSheet()
        
        # Custom styles
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=24,
            textColor=colors.HexColor('#2C3E50'),
            spaceAfter=30,
            alignment=TA_CENTER
        )
        
        heading_style = ParagraphStyle(
            'CustomHeading',
            parent=styles['Heading2'],
            fontSize=14,
            textColor=colors.HexColor('#34495E'),
            spaceAfter=12,
            spaceBefore=12
        )
        
        subheading_style = ParagraphStyle(
            'CustomSubHeading',
            parent=styles['Heading3'],
            fontSize=12,
            textColor=colors.HexColor('#34495E'),
            spaceAfter=8,
            spaceBefore=8
        )
        
        # Title
        story.append(Paragraph(f"Kubernetes Health Check Report", title_style))
        story.append(Paragraph(f"Namespace: {self.namespace}", styles['Normal']))
        story.append(Paragraph(f"Generated: {self.timestamp.strftime('%Y-%m-%d %H:%M:%S')}", styles['Normal']))
        story.append(Spacer(1, 0.5*inch))
        
        # Executive Summary
        story.append(Paragraph("Executive Summary", heading_style))
        summary_data = self._generate_summary()
        story.append(Paragraph(summary_data, styles['Normal']))
        story.append(Spacer(1, 0.3*inch))
        
        # Statistics Overview
        story.append(Paragraph("Statistics Overview", heading_style))
        stats_table = self._create_stats_table()
        if stats_table:
            story.append(stats_table)
            story.append(Spacer(1, 0.3*inch))
        
        # Health Check Results
        if self.report_data['health_results']:
            story.append(Paragraph("Services with Health Endpoints", heading_style))
            health_table = self._create_results_table(self.report_data['health_results'])
            story.append(health_table)
            story.append(Spacer(1, 0.3*inch))
        
        # Basic Connectivity Results
        if self.report_data['basic_results']:
            story.append(Paragraph("Services with Basic Connectivity", heading_style))
            basic_table = self._create_results_table(self.report_data['basic_results'])
            story.append(basic_table)
            story.append(Spacer(1, 0.3*inch))
        
        # Service Categories
        self._add_service_categories_to_story(story, heading_style, subheading_style)
        
        # Issues and Recommendations
        if self.report_data['issues']:
            story.append(Paragraph("Issues and Recommendations", heading_style))
            for issue in self.report_data['issues']:
                story.append(Paragraph(f"• {issue}", styles['Normal']))
            story.append(Spacer(1, 0.3*inch))
        
        # Build PDF
        doc.build(story)
        print(f"{C.G}✅ PDF report generated: {filepath}{C.E}")
        return str(filepath)
    
    def _add_service_categories_to_story(self, story, heading_style, subheading_style):
        """Add all service categories as separate tables"""
        categories = self.report_data['service_categories']
        
        if not any(categories.values()):
            return
        
        story.append(Paragraph("Service Categories", heading_style))
        
        # Suspended Services
        if categories.get('suspended_services'):
            story.append(Paragraph("Suspended Services (0 pods)", subheading_style))
            suspended_table = self._create_simple_service_table(categories['suspended_services'])
            story.append(suspended_table)
            story.append(Spacer(1, 0.2*inch))
        
        # Services without Selector
        if categories.get('services_no_selector'):
            story.append(Paragraph("Services without Selector", subheading_style))
            no_selector_table = self._create_simple_service_table(categories['services_no_selector'])
            story.append(no_selector_table)
            story.append(Spacer(1, 0.2*inch))
        
        # Services without Health Probe
        if categories.get('services_no_health_probe'):
            story.append(Paragraph("Services without Health Probe", subheading_style))
            no_probe_table = self._create_simple_service_table(categories['services_no_health_probe'])
            story.append(no_probe_table)
            story.append(Spacer(1, 0.2*inch))
        
        # Services without Ingress
        if categories.get('services_no_ingress'):
            story.append(Paragraph("Services without Ingress Route", subheading_style))
            no_ingress_table = self._create_simple_service_table(categories['services_no_ingress'])
            story.append(no_ingress_table)
            story.append(Spacer(1, 0.2*inch))
    
    def _create_simple_service_table(self, services):
        """Create a simple table for service lists"""
        if not services:
            return None
        
        # Create data in columns of 3
        data = [['Service Name', 'Service Name', 'Service Name']]
        
        # Pad services list to make it divisible by 3
        services_padded = services + [''] * (3 - len(services) % 3)
        
        # Group into rows of 3
        for i in range(0, len(services_padded), 3):
            row = services_padded[i:i+3]
            if any(row):  # Only add non-empty rows
                data.append(row)
        
        table = Table(data, colWidths=[2.5*inch, 2.5*inch, 2.5*inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('VALIGN', (0, 0), (-1, -1), 'TOP')
        ]))
        
        return table
    
    def _generate_summary(self):
        """Generate executive summary"""
        stats = self.report_data['statistics']
        
        total_services = stats.get('total_services', 0)
        healthy_services = stats.get('healthy_services', 0)
        services_with_issues = stats.get('services_with_issues', 0)
        
        if total_services > 0:
            health_rate = (healthy_services / total_services) * 100
        else:
            health_rate = 0
        
        summary = f"""
        This report provides a comprehensive health check of all services in the '{self.namespace}' namespace.
        
        Total Services: {total_services}
        Healthy Services: {healthy_services} ({health_rate:.1f}%)
        Services with Issues: {services_with_issues}
        
        Overall Status: {'✅ Healthy' if health_rate >= 90 else '⚠️ Degraded' if health_rate >= 70 else '❌ Critical'}
        
        The report categorizes services based on their health check capabilities and connectivity status.
        """
        
        return summary
    
    def _create_stats_table(self):
        """Create statistics table for PDF"""
        stats = self.report_data['statistics']
        categories = self.report_data['service_categories']
        
        data = [
            ['Metric', 'Count'],
            ['Total Services', str(stats.get('total_services', 0))],
            ['Healthy Services', str(stats.get('healthy_services', 0))],
            ['Services with Issues', str(stats.get('services_with_issues', 0))],
            ['Suspended Services', str(len(categories.get('suspended_services', [])))],
            ['Services without Health Probe', str(len(categories.get('services_no_health_probe', [])))],
            ['Services without Ingress', str(len(categories.get('services_no_ingress', [])))],
            ['Services without Selector', str(len(categories.get('services_no_selector', [])))]
        ]
        
        table = Table(data, colWidths=[4*inch, 2*inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 12),
            ('FONTSIZE', (0, 1), (-1, -1), 11),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        
        return table
    
    def _create_results_table(self, results):
        """Create results table for PDF"""
        if not results:
            return None
        
        # Clean data for PDF (remove ANSI colors)
        clean_data = [['Service', 'Status', 'Pods', 'Faulty Pods']]
        
        for row in results:
            clean_row = []
            for cell in row:
                # Remove ANSI color codes and emojis for cleaner PDF
                clean_cell = str(cell)
                # Remove ANSI codes
                import re
                clean_cell = re.sub(r'\033\[[0-9;]+m', '', clean_cell)
                clean_row.append(clean_cell)
            clean_data.append(clean_row)
        
        table = Table(clean_data, colWidths=[2*inch, 1.5*inch, 0.8*inch, 2.7*inch])
        
        # Determine row colors based on status
        style_commands = [
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('ALIGN', (2, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('VALIGN', (0, 0), (-1, -1), 'TOP')
        ]
        
        # Add row coloring based on status
        for i, row in enumerate(clean_data[1:], start=1):
            status = row[1]
            if 'UP' in status or 'ACCESSIBLE' in status:
                style_commands.append(('BACKGROUND', (1, i), (1, i), colors.lightgreen))
            elif 'DOWN' in status or 'ERROR' in status or 'TIMEOUT' in status:
                style_commands.append(('BACKGROUND', (1, i), (1, i), colors.lightcoral))
            else:
                style_commands.append(('BACKGROUND', (1, i), (1, i), colors.lightyellow))
        
        table.setStyle(TableStyle(style_commands))
        return table
    
    def add_health_results(self, results, healthy_count, total_tested):
        """Add health check results to report"""
        self.report_data['health_results'] = results
        self.report_data['statistics']['healthy_services'] = healthy_count
        self.report_data['statistics']['total_tested'] = total_tested
        
    def add_basic_results(self, results):
        """Add basic connectivity results to report"""
        self.report_data['basic_results'] = results
        
    def add_statistics(self, stats):
        """Add statistics to report"""
        self.report_data['statistics'].update(stats)
        
    def add_service_categories(self, categories):
        """Add service categories to report"""
        self.report_data['service_categories'] = categories
        
    def add_issue(self, issue):
        """Add an issue/recommendation to report"""
        self.report_data['issues'].append(issue)

# Original functions with minor modifications to support reporting
def get_pod_stats(pods, selector):
    """Get pod statistics for a service"""
    matching_pods = [pod for pod in pods.items 
                    if all((pod.metadata.labels or {}).get(k) == v for k, v in selector.items())]
    
    total_pods = len(matching_pods)
    faulty_pod_names = []
    
    for pod in matching_pods:
        is_faulty = False
        pod_name = pod.metadata.name
        
        if pod.status.phase in ['Failed', 'Pending']:
            is_faulty = True
        
        if pod.status.container_statuses:
            for container in pod.status.container_statuses:
                if container.restart_count > 3 and not container.ready:
                    is_faulty = True
                
                if (container.state and container.state.waiting and 
                    container.state.waiting.reason == 'CrashLoopBackOff'):
                    is_faulty = True
                
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
    basic_endpoints = {}
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
        
        total_pods, faulty_pod_names, matching_pods = get_pod_stats(pods, selector)
        
        if total_pods == 0:
            suspended_services.append(svc_name)
            continue
            
        health_path = None
        for pod in matching_pods:
            for container in pod.spec.containers:
                for probe in [container.liveness_probe, container.readiness_probe]:
                    if probe and probe.http_get and probe.http_get.path:
                        probe_path = probe.http_get.path
                        if "/actuator/health" in probe_path or probe_path in ["/ping", "ping", "/health", "health"]:
                            health_path = probe_path
                            break
                if health_path:
                    break
            if health_path:
                break
        
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
            health_endpoints[svc_name] = {
                'service': svc_name,
                'endpoint': f"{ingress_endpoint}{health_path}",
                'total_pods': total_pods,
                'faulty_pod_names': faulty_pod_names
            }
        elif ingress_endpoint and not health_path:
            basic_endpoints[svc_name] = {
                'service': svc_name,
                'endpoint': ingress_endpoint,
                'total_pods': total_pods,
                'faulty_pod_names': faulty_pod_names
            }
        elif health_path and not ingress_endpoint:
            services_no_ingress.append(svc_name)
        else:
            services_no_health_probe.append(svc_name)
    
    return (list(health_endpoints.values()), 
            list(basic_endpoints.values()),
            services_no_selector, 
            services_no_health_probe,
            services_no_ingress,
            suspended_services)

def check_health_endpoints(endpoints, namespace, report=None):
    """Check health endpoints"""
    if not endpoints:
        return [], 0
    
    print(f"\n{C.B}{C.C}🏥 Health Check: {namespace} ({len(endpoints)} endpoints){C.E}")
    print(f"{C.C}{'─' * 70}{C.E}")
    
    results = []
    healthy_count = 0
    
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
                    
                    if 'status' in health_data:
                        status = health_data.get('status', 'UNKNOWN')
                    elif 'pong' in health_data:
                        pong_value = health_data.get('pong')
                        if pong_value is True or str(pong_value).lower() == 'true':
                            status = 'UP'
                        else:
                            status = 'DOWN'
                    else:
                        status = 'UP'
                    
                except json.JSONDecodeError:
                    status = 'UP'
                
                if status == 'UP':
                    print(f"{C.G}✅ UP{C.E}")
                    health_status, healthy_count = '🟢 UP', healthy_count + 1
                else:
                    print(f"{C.Y}⚠️  {status}{C.E}")
                    health_status = f'🟡 {status}'
                    if report:
                        report.add_issue(f"Service {service_name} returned status: {status}")
            else:
                print(f"{C.R}❌ HTTP {response.status_code}{C.E}")
                health_status = '🔴 ERROR'
                if report:
                    report.add_issue(f"Service {service_name} returned HTTP {response.status_code}")
            
            if faulty_pod_names:
                fault_count = len(faulty_pod_names)
                faulty_display = f"{C.R}{fault_count}: {', '.join(faulty_pod_names)}{C.E}"
                if report and fault_count > 0:
                    report.add_issue(f"Service {service_name} has {fault_count} faulty pods")
            else:
                faulty_display = f"{C.G}0: None{C.E}"
            
            results.append([service_name, health_status, str(total_pods), faulty_display])
            
        except requests.exceptions.Timeout:
            print(f"{C.R}⏱️  TIMEOUT{C.E}")
            fault_count = len(faulty_pod_names)
            faulty_display = f"{C.R}{fault_count}: {', '.join(faulty_pod_names)}{C.E}" if faulty_pod_names else f"{C.G}0: None{C.E}"
            results.append([service_name, '🔴 TIMEOUT', str(total_pods), faulty_display])
            if report:
                report.add_issue(f"Service {service_name} timed out during health check")
        except requests.exceptions.ConnectionError:
            print(f"{C.R}🚫 UNREACHABLE{C.E}")
            fault_count = len(faulty_pod_names)
            faulty_display = f"{C.R}{fault_count}: {', '.join(faulty_pod_names)}{C.E}" if faulty_pod_names else f"{C.G}0: None{C.E}"
            results.append([service_name, '🔴 UNREACHABLE', str(total_pods), faulty_display])
            if report:
                report.add_issue(f"Service {service_name} is unreachable")
        except Exception as e:
            print(f"{C.R}💥 ERROR{C.E}")
            fault_count = len(faulty_pod_names)
            faulty_display = f"{C.R}{fault_count}: {', '.join(faulty_pod_names)}{C.E}" if faulty_pod_names else f"{C.G}0: None{C.E}"
            results.append([service_name, '🔴 ERROR', str(total_pods), faulty_display])
            if report:
                report.add_issue(f"Service {service_name} error: {str(e)}")
    
    return results, healthy_count

def check_basic_connectivity(basic_endpoints, namespace, report=None):
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
            
            if response.status_code in [200, 301, 302, 403]:
                print(f"{C.G}✅ ACCESSIBLE{C.E}")
                connectivity_status = '🟢 ACCESSIBLE'
            elif response.status_code in [404]:
                print(f"{C.Y}⚠️  NOT FOUND{C.E}")
                connectivity_status = '🟡 NOT FOUND'
                if report:
                    report.add_issue(f"Service {service_name} returned 404")
            else:
                print(f"{C.R}❌ HTTP {response.status_code}{C.E}")
                connectivity_status = f'🔴 HTTP {response.status_code}'
                if report:
                    report.add_issue(f"Service {service_name} returned HTTP {response.status_code}")
            
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
            if report:
                report.add_issue(f"Service {service_name} timed out")
        except requests.exceptions.ConnectionError:
            print(f"{C.R}🚫 UNREACHABLE{C.E}")
            fault_count = len(faulty_pod_names)
            faulty_display = f"{C.R}{fault_count}: {', '.join(faulty_pod_names)}{C.E}" if faulty_pod_names else f"{C.G}0: None{C.E}"
            results.append([service_name, '🔴 UNREACHABLE', str(total_pods), faulty_display])
            if report:
                report.add_issue(f"Service {service_name} is unreachable")
        except Exception as e:
            print(f"{C.R}💥 ERROR{C.E}")
            fault_count = len(faulty_pod_names)
            faulty_display = f"{C.R}{fault_count}: {', '.join(faulty_pod_names)}{C.E}" if faulty_pod_names else f"{C.G}0: None{C.E}"
            results.append([service_name, '🔴 ERROR', str(total_pods), faulty_display])
            if report:
                report.add_issue(f"Service {service_name} error: {str(e)}")
    
    return results

def print_results(health_results, healthy_count, basic_results, services_no_selector, services_no_health_probe, services_no_ingress, suspended_services):
    # Health check results
    if health_results:
        total_endpoints = len(health_results)
        success_rate = (healthy_count/total_endpoints)*100
        
        print(f"\n{C.B}📊 Health Check Results{C.E}")
        print(tabulate(health_results, headers=['Service', 'Status', 'Total Pods', 'Faulty Pods'], tablefmt='simple'))
        
        print(f"\n{C.B}Health Stats:{C.E} {C.G}{healthy_count}/{total_endpoints} healthy{C.E} ({success_rate:.0f}%)")
    
    # Basic connectivity results
    if basic_results:
        print(f"\n{C.B}🌐 Basic Connectivity Results{C.E}")
        print(tabulate(basic_results, headers=['Service', 'Status', 'Total Pods', 'Faulty Pods'], tablefmt='simple'))
        
        accessible_count = sum(1 for r in basic_results if 'ACCESSIBLE' in r[1])
        total_basic = len(basic_results)
        basic_success_rate = (accessible_count/total_basic)*100
        print(f"\n{C.B}Connectivity Stats:{C.E} {C.G}{accessible_count}/{total_basic} accessible{C.E} ({basic_success_rate:.0f}%)")
    
    # Services categorization - FULL LISTS
    if any([suspended_services, services_no_selector, services_no_health_probe, services_no_ingress]):
        print(f"\n{C.B}📋 Service Categories{C.E}")
        
        if suspended_services:
            print(f"\n{C.R}🛑 Suspended Services (0 pods): {len(suspended_services)}{C.E}")
            for svc in suspended_services:  # Show ALL, not truncated
                print(f"  • {svc}")
        
        if services_no_selector:
            print(f"\n{C.Y}🔸 No Selector: {len(services_no_selector)}{C.E}")
            for svc in services_no_selector:  # Show ALL, not truncated
                print(f"  • {svc}")
        
        if services_no_health_probe:
            print(f"\n{C.Y}🔸 No Health Probe: {len(services_no_health_probe)}{C.E}")
            for svc in services_no_health_probe:  # Show ALL, not truncated
                print(f"  • {svc}")
        
        if services_no_ingress:
            print(f"\n{C.Y}🔸 No Ingress Route: {len(services_no_ingress)}{C.E}")
            for svc in services_no_ingress:  # Show ALL, not truncated
                print(f"  • {svc}")
    
    # Overall health status
    if health_results:
        success_rate = (healthy_count/len(health_results))*100
        if success_rate >= 90:
            print(f"\n{C.G}🎉 System healthy{C.E}")
        elif success_rate >= 70:
            print(f"\n{C.Y}⚠️  Some issues detected{C.E}")
        else:
            print(f"\n{C.R}🚨 Multiple services down{C.E}")

def generate_junit_xml(namespace, health_results, basic_results, output_dir="reports"):
    """Generate JUnit XML for GitLab CI integration"""
    from xml.etree.ElementTree import Element, SubElement, tostring
    from xml.dom import minidom
    
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    testsuites = Element('testsuites')
    testsuite = SubElement(testsuites, 'testsuite')
    testsuite.set('name', f'K8s Health Check - {namespace}')
    testsuite.set('timestamp', datetime.now().isoformat())
    
    test_count = 0
    failure_count = 0
    
    # Add health check tests
    for result in health_results:
        test_count += 1
        testcase = SubElement(testsuite, 'testcase')
        testcase.set('classname', f'{namespace}.health')
        testcase.set('name', result[0])
        
        if '🔴' in result[1] or 'ERROR' in result[1] or 'TIMEOUT' in result[1]:
            failure_count += 1
            failure = SubElement(testcase, 'failure')
            failure.set('message', f'Service unhealthy: {result[1]}')
            failure.text = f'Service {result[0]} is not healthy. Status: {result[1]}'
    
    # Add basic connectivity tests
    for result in basic_results:
        test_count += 1
        testcase = SubElement(testsuite, 'testcase')
        testcase.set('classname', f'{namespace}.connectivity')
        testcase.set('name', result[0])
        
        if '🔴' in result[1] or 'ERROR' in result[1] or 'TIMEOUT' in result[1]:
            failure_count += 1
            failure = SubElement(testcase, 'failure')
            failure.set('message', f'Service unreachable: {result[1]}')
            failure.text = f'Service {result[0]} is not accessible. Status: {result[1]}'
    
    testsuite.set('tests', str(test_count))
    testsuite.set('failures', str(failure_count))
    
    # Pretty print XML
    rough_string = tostring(testsuites, 'utf-8')
    reparsed = minidom.parseString(rough_string)
    
    junit_file = output_dir / 'junit.xml'
    with open(junit_file, 'w') as f:
        f.write(reparsed.toprettyxml(indent="  "))
    
    print(f"{C.G}✅ JUnit XML generated: {junit_file}{C.E}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="K8s health check monitor with reporting")
    parser.add_argument("namespace", help="Kubernetes namespace")
    parser.add_argument("--output-format", choices=['console', 'pdf', 'both'], 
                       default='console', help="Output format")
    parser.add_argument("--output-dir", default="reports", 
                       help="Directory for reports (default: reports)")
    args = parser.parse_args()
    
    try:
        # Initialize report if needed
        report = None
        if args.output_format in ['pdf', 'both']:
            report = HealthCheckReport(args.namespace, args.output_dir)
        
        # Get endpoints
        (health_endpoints, basic_endpoints, services_no_selector, 
         services_no_health_probe, services_no_ingress, suspended_services) = get_health_check_endpoints(args.namespace)
        
        # Check health endpoints
        health_results, healthy_count = check_health_endpoints(health_endpoints, args.namespace, report)
        
        # Check basic connectivity
        basic_results = check_basic_connectivity(basic_endpoints, args.namespace, report)
        
        # Console output
        if args.output_format in ['console', 'both']:
            print_results(health_results, healthy_count, basic_results, 
                         services_no_selector, services_no_health_probe, 
                         services_no_ingress, suspended_services)
        
        # Generate reports
        if args.output_format in ['pdf', 'both'] and report:
            # Calculate correct statistics
            total_services = (len(health_results) + len(basic_results) + 
                            len(suspended_services) + len(services_no_selector) + 
                            len(services_no_health_probe) + len(services_no_ingress))
            
            services_with_issues = len(health_results) + len(basic_results) - healthy_count
            
            # Add data to report
            report.add_health_results(health_results, healthy_count, len(health_results))
            report.add_basic_results(basic_results)
            report.add_statistics({
                'total_services': total_services,
                'services_with_issues': services_with_issues
            })
            report.add_service_categories({
                'suspended_services': suspended_services,
                'services_no_selector': services_no_selector,
                'services_no_health_probe': services_no_health_probe,
                'services_no_ingress': services_no_ingress
            })
            
            # Generate PDF
            report.generate_pdf()
        
        # Generate JUnit XML for GitLab CI
        if os.getenv('CI'):  # Only in CI environment
            generate_junit_xml(args.namespace, health_results, basic_results, args.output_dir)
        
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"\n{C.C}✨ Completed at {timestamp}{C.E}")
        
        # Exit with error code if health is critical
        if health_results:
            success_rate = (healthy_count/len(health_results))*100
            if success_rate < 70:
                sys.exit(1)  # Exit with error for CI/CD
        
    except Exception as e:
        print(f"{C.R}❌ Error: {str(e)}{C.E}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
