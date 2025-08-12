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
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_CENTER, TA_LEFT
import sys
import re

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ANSI colors
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
        
    def generate_pdf(self, health_results, healthy_count, basic_results, 
                    services_no_selector, services_no_health_probe, 
                    services_no_ingress, suspended_services, filename=None):
        """Generate PDF report"""
        if not filename:
            filename = f"k8s_health_report_{self.namespace}_{self.timestamp.strftime('%Y%m%d_%H%M%S')}.pdf"
        
        filepath = self.output_dir / filename
        doc = SimpleDocTemplate(str(filepath), pagesize=A4, 
                              leftMargin=0.5*inch, rightMargin=0.5*inch,
                              topMargin=0.5*inch, bottomMargin=0.5*inch)
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
        summary = self._generate_summary(health_results, healthy_count, basic_results,
                                       services_no_selector, services_no_health_probe,
                                       services_no_ingress, suspended_services)
        story.append(Paragraph(summary, styles['Normal']))
        story.append(Spacer(1, 0.3*inch))
        
        # Statistics Overview
        story.append(Paragraph("Statistics Overview", heading_style))
        stats_table = self._create_stats_table(health_results, healthy_count, basic_results,
                                              services_no_selector, services_no_health_probe,
                                              services_no_ingress, suspended_services)
        story.append(stats_table)
        story.append(Spacer(1, 0.3*inch))
        
        # Health Check Results
        if health_results:
            story.append(Paragraph("Services with Health Endpoints", heading_style))
            health_table = self._create_results_table(health_results, "Health Check Results")
            story.append(health_table)
            story.append(Spacer(1, 0.3*inch))
        
        # Basic Connectivity Results
        if basic_results:
            story.append(Paragraph("Services with Basic Connectivity", heading_style))
            basic_table = self._create_results_table(basic_results, "Basic Connectivity")
            story.append(basic_table)
            story.append(Spacer(1, 0.3*inch))
        
        # Service Categories - ALL COMPLETE LISTS
        story.append(Paragraph("Service Categories", heading_style))
        
        if suspended_services:
            story.append(Paragraph("Suspended Services (0 pods)", subheading_style))
            suspended_table = self._create_service_list_table(suspended_services)
            story.append(suspended_table)
            story.append(Spacer(1, 0.2*inch))
        
        if services_no_selector:
            story.append(Paragraph("Services without Selector", subheading_style))
            no_selector_table = self._create_service_list_table(services_no_selector)
            story.append(no_selector_table)
            story.append(Spacer(1, 0.2*inch))
        
        if services_no_health_probe:
            story.append(Paragraph("Services without Health Probe", subheading_style))
            no_probe_table = self._create_service_list_table(services_no_health_probe)
            story.append(no_probe_table)
            story.append(Spacer(1, 0.2*inch))
        
        if services_no_ingress:
            story.append(Paragraph("Services without Ingress Route", subheading_style))
            no_ingress_table = self._create_service_list_table(services_no_ingress)
            story.append(no_ingress_table)
            story.append(Spacer(1, 0.2*inch))
        
        # Build PDF
        doc.build(story)
        print(f"{C.G}✅ PDF report generated: {filepath}{C.E}")
        return str(filepath)
    
    def _generate_summary(self, health_results, healthy_count, basic_results,
                         services_no_selector, services_no_health_probe,
                         services_no_ingress, suspended_services):
        """Generate executive summary"""
        total_services = (len(health_results) + len(basic_results) + 
                         len(suspended_services) + len(services_no_selector) + 
                         len(services_no_health_probe) + len(services_no_ingress))
        
        if health_results:
            health_rate = (healthy_count / len(health_results)) * 100
        else:
            health_rate = 0
        
        accessible_count = sum(1 for r in basic_results if 'ACCESSIBLE' in r[1]) if basic_results else 0
        
        summary = f"""
        This report provides a comprehensive health check of all services in the '{self.namespace}' namespace.
        
        Total Services: {total_services}
        Services with Health Endpoints: {len(health_results)} (Healthy: {healthy_count})
        Services with Basic Connectivity: {len(basic_results)} (Accessible: {accessible_count})
        Suspended Services: {len(suspended_services)}
        Services without Health Probe: {len(services_no_health_probe)}
        Services without Ingress: {len(services_no_ingress)}
        Services without Selector: {len(services_no_selector)}
        
        Overall Health Rate: {health_rate:.1f}%
        Overall Status: {'✅ Healthy' if health_rate >= 90 else '⚠️ Degraded' if health_rate >= 70 else '❌ Critical'}
        """
        
        return summary
    
    def _create_stats_table(self, health_results, healthy_count, basic_results,
                           services_no_selector, services_no_health_probe,
                           services_no_ingress, suspended_services):
        """Create statistics table for PDF"""
        total_services = (len(health_results) + len(basic_results) + 
                         len(suspended_services) + len(services_no_selector) + 
                         len(services_no_health_probe) + len(services_no_ingress))
        
        accessible_count = sum(1 for r in basic_results if 'ACCESSIBLE' in r[1]) if basic_results else 0
        
        data = [
            ['Metric', 'Count'],
            ['Total Services', str(total_services)],
            ['Services with Health Endpoints', str(len(health_results))],
            ['Healthy Services', str(healthy_count)],
            ['Services with Basic Connectivity', str(len(basic_results))],
            ['Accessible Services', str(accessible_count)],
            ['Suspended Services', str(len(suspended_services))],
            ['Services without Health Probe', str(len(services_no_health_probe))],
            ['Services without Ingress', str(len(services_no_ingress))],
            ['Services without Selector', str(len(services_no_selector))]
        ]
        
        table = Table(data, colWidths=[4.5*inch, 2*inch])
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
    
    def _create_results_table(self, results, table_type):
        """Create results table for PDF with proper text wrapping"""
        if not results:
            return None
        
        # Clean data for PDF (remove ANSI colors and handle long text)
        clean_data = [['Service', 'Status', 'Pods', 'Faulty Pods']]
        
        for row in results:
            clean_row = []
            for i, cell in enumerate(row):
                # Remove ANSI color codes
                clean_cell = str(cell)
                clean_cell = re.sub(r'\033\[[0-9;]+m', '', clean_cell)
                
                # Handle long faulty pod names in the last column
                if i == 3 and len(clean_cell) > 40:  # Faulty pods column
                    # Split long pod names list
                    if ':' in clean_cell:
                        parts = clean_cell.split(':', 1)
                        if len(parts) > 1:
                            count_part = parts[0]
                            pod_names = parts[1].strip()
                            
                            # Break long pod names into multiple lines
                            if len(pod_names) > 40:
                                pod_list = pod_names.split(', ')
                                formatted_pods = []
                                current_line = ""
                                
                                for pod in pod_list:
                                    if len(current_line + pod) < 35:
                                        current_line += pod + ", "
                                    else:
                                        if current_line:
                                            formatted_pods.append(current_line.rstrip(', '))
                                        current_line = pod + ", "
                                
                                if current_line:
                                    formatted_pods.append(current_line.rstrip(', '))
                                
                                clean_cell = count_part + ": " + "\n".join(formatted_pods)
                
                clean_row.append(clean_cell)
            clean_data.append(clean_row)
        
        # Adjust column widths for better fit
        table = Table(clean_data, colWidths=[2*inch, 1.3*inch, 0.7*inch, 3*inch])
        
        # Style commands
        style_commands = [
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('ALIGN', (2, 0), (-1, -1), 'CENTER'),  # Center align pod count
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('FONTSIZE', (0, 1), (-1, -1), 8),  # Smaller font for content
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.beige, colors.white])
        ]
        
        # Add row coloring based on status
        for i, row in enumerate(clean_data[1:], start=1):
            status = row[1]
            if 'UP' in status or 'ACCESSIBLE' in status:
                style_commands.append(('BACKGROUND', (1, i), (1, i), colors.lightgreen))
            elif 'DOWN' in status or 'ERROR' in status or 'TIMEOUT' in status or 'UNREACHABLE' in status:
                style_commands.append(('BACKGROUND', (1, i), (1, i), colors.lightcoral))
            else:
                style_commands.append(('BACKGROUND', (1, i), (1, i), colors.lightyellow))
        
        table.setStyle(TableStyle(style_commands))
        return table
    
    def _create_service_list_table(self, services):
        """Create a table for service lists with 4 columns"""
        if not services:
            return Paragraph("No services in this category.", getSampleStyleSheet()['Normal'])
        
        # Create data in columns of 4
        data = [['Service Name', 'Service Name', 'Service Name', 'Service Name']]
        
        # Pad services list to make it divisible by 4
        services_padded = services + [''] * (4 - len(services) % 4) if len(services) % 4 != 0 else services
        
        # Group into rows of 4
        for i in range(0, len(services_padded), 4):
            row = services_padded[i:i+4]
            if any(row):  # Only add non-empty rows
                data.append(row)
        
        table = Table(data, colWidths=[1.8*inch, 1.8*inch, 1.8*inch, 1.8*inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('VALIGN', (0, 0), (-1, -1), 'TOP')
        ]))
        
        return table

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
            basic_endpoints[svc_name] = {
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
            list(basic_endpoints.values()),
            services_no_selector, 
            services_no_health_probe,
            services_no_ingress,
            suspended_services)

def check_health_endpoints(endpoints, namespace):
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
                health_status = '🔴 ERROR'
            
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
    
    # Services categorization - SHOW ALL SERVICES (NO TRUNCATION)
    if any([suspended_services, services_no_selector, services_no_health_probe, services_no_ingress]):
        print(f"\n{C.B}📋 Service Categories{C.E}")
        
        if suspended_services:
            print(f"\n{C.R}🛑 Suspended Services (0 pods): {len(suspended_services)}{C.E}")
            for svc in suspended_services:  # Show ALL services
                print(f"  • {svc}")
        
        if services_no_selector:
            print(f"\n{C.Y}🔸 No Selector: {len(services_no_selector)}{C.E}")
            for svc in services_no_selector:  # Show ALL services
                print(f"  • {svc}")
        
        if services_no_health_probe:
            print(f"\n{C.Y}🔸 No Health Probe: {len(services_no_health_probe)}{C.E}")
            for svc in services_no_health_probe:  # Show ALL services
                print(f"  • {svc}")
        
        if services_no_ingress:
            print(f"\n{C.Y}🔸 No Ingress Route: {len(services_no_ingress)}{C.E}")
            for svc in services_no_ingress:  # Show ALL services
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

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="K8s health check monitor")
    parser.add_argument("namespace", help="Kubernetes namespace")
    parser.add_argument("--output-format", choices=['console', 'pdf', 'both'], 
                       default='console', help="Output format (default: console)")
    parser.add_argument("--output-dir", default="reports", 
                       help="Directory for reports (default: reports)")
    args = parser.parse_args()
    
    try:
        (health_endpoints, basic_endpoints, services_no_selector, 
         services_no_health_probe, services_no_ingress, suspended_services) = get_health_check_endpoints(args.namespace)
        
        # Check health endpoints
        health_results, healthy_count = check_health_endpoints(health_endpoints, args.namespace)
        
        # Check basic connectivity for services without health probes
        basic_results = check_basic_connectivity(basic_endpoints, args.namespace)
        
        # Console output
        if args.output_format in ['console', 'both']:
            print_results(health_results, healthy_count, basic_results, 
                         services_no_selector, services_no_health_probe, 
                         services_no_ingress, suspended_services)
        
        # Generate PDF report
        if args.output_format in ['pdf', 'both']:
            report = HealthCheckReport(args.namespace, args.output_dir)
            report.generate_pdf(health_results, healthy_count, basic_results,
                              services_no_selector, services_no_health_probe,
                              services_no_ingress, suspended_services)
        
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"\n{C.C}✨ Completed at {timestamp}{C.E}")
        
    except Exception as e:
        print(f"{C.R}❌ Error: {str(e)}{C.E}")
        import traceback
        traceback.print_exc()
