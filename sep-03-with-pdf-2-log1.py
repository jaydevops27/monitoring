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
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY
import sys
import re
import yaml

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
        
    def _wrap_text(self, text, max_length=25):
        """Wrap text to fit in table cells"""
        if len(text) <= max_length:
            return text
        
        # For service names, wrap at logical points
        if '.' in text or '-' in text:
            parts = re.split(r'([.-])', text)
            result = ""
            current_line = ""
            
            for part in parts:
                if len(current_line + part) <= max_length:
                    current_line += part
                else:
                    if current_line:
                        result += current_line + "\n"
                    current_line = part
            
            if current_line:
                result += current_line
            
            return result
        else:
            # Simple character-based wrapping
            lines = []
            for i in range(0, len(text), max_length):
                lines.append(text[i:i+max_length])
            return "\n".join(lines)
        
    def generate_pdf(self, health_results, healthy_count, basic_results, 
                    services_no_selector, services_no_health_probe, 
                    services_no_ingress, suspended_services, filename=None):
        """Generate professional organizational PDF report"""
        if not filename:
            filename = f"k8s_health_report_{self.namespace}_{self.timestamp.strftime('%Y%m%d_%H%M%S')}.pdf"
        
        filepath = self.output_dir / filename
        doc = SimpleDocTemplate(str(filepath), pagesize=A4, 
                              leftMargin=0.4*inch, rightMargin=0.4*inch,
                              topMargin=0.5*inch, bottomMargin=0.5*inch)
        story = []
        styles = getSampleStyleSheet()
        
        # T-Mobile color scheme - Professional styles with consistent sizing
        tmobile_magenta = colors.HexColor('#E20074')
        tmobile_dark = colors.HexColor('#666666')
        
        title_style = ParagraphStyle(
            'Title',
            parent=styles['Heading1'],
            fontSize=20,
            textColor=tmobile_magenta,
            spaceAfter=5,
            alignment=TA_CENTER,
            fontName='Helvetica-Bold'
        )
        
        subtitle_style = ParagraphStyle(
            'Subtitle',
            parent=styles['Normal'],
            fontSize=10,
            textColor=tmobile_dark,
            spaceAfter=20,
            alignment=TA_CENTER,
            fontName='Helvetica'
        )
        
        heading_style = ParagraphStyle(
            'Heading',
            parent=styles['Heading2'],
            fontSize=12,
            textColor=tmobile_magenta,
            spaceAfter=8,
            spaceBefore=15,
            fontName='Helvetica-Bold'
        )
        
        subheading_style = ParagraphStyle(
            'SubHeading',
            parent=styles['Heading3'],
            fontSize=10,
            textColor=tmobile_dark,
            spaceAfter=6,
            spaceBefore=10,
            fontName='Helvetica-Bold'
        )
        
        # Header with clean layout
        story.append(Paragraph("Kubernetes Health Report", title_style))
        story.append(Paragraph(f"Namespace: <b>{self.namespace}</b> | {self.timestamp.strftime('%Y-%m-%d %H:%M')}", subtitle_style))
        
        # Status Overview Box
        status_overview = self._create_status_overview_box(health_results, healthy_count, basic_results, suspended_services)
        story.append(status_overview)
        story.append(Spacer(1, 0.15*inch))
        
        # Key Metrics Overview
        story.append(Paragraph("Service Metrics", heading_style))
        stats_table = self._create_tmobile_stats_table(health_results, healthy_count, basic_results,
                                                     services_no_selector, services_no_health_probe,
                                                     services_no_ingress, suspended_services)
        story.append(stats_table)
        story.append(Spacer(1, 0.15*inch))
        
        # Service Status Tables - Organized by category
        if health_results:
            story.append(Paragraph("Health Monitored Services", heading_style))
            health_table = self._create_tmobile_results_table(health_results)
            story.append(health_table)
            story.append(Spacer(1, 0.1*inch))
        
        if basic_results:
            story.append(Paragraph("Basic Connectivity Services", heading_style))
            basic_table = self._create_tmobile_results_table(basic_results)
            story.append(basic_table)
            story.append(Spacer(1, 0.1*inch))
        
        # Service Categories - Clean and organized
        if any([suspended_services, services_no_health_probe, services_no_ingress, services_no_selector]):
            story.append(Paragraph("Service Categories", heading_style))
            
            categories = [
                ("Suspended Services", suspended_services, "Services with zero pods"),
                ("Services Without Health Probes", services_no_health_probe, "Missing health monitoring"),
                ("Services Without Ingress", services_no_ingress, "No external access configured"),
                ("Services Without Selectors", services_no_selector, "Invalid service configuration")
            ]
            
            for title, services, description in categories:
                if services:
                    story.append(Paragraph(f"{title} ({len(services)})", subheading_style))
                    service_table = self._create_tmobile_service_table(services)
                    story.append(service_table)
                    story.append(Spacer(1, 0.08*inch))
        
        # Clean footer
        story.append(Spacer(1, 0.2*inch))
        footer_style = ParagraphStyle('Footer', parent=styles['Normal'], fontSize=8, 
                                    textColor=tmobile_dark, alignment=TA_CENTER)
        story.append(Paragraph(f"Generated: {self.timestamp.strftime('%Y-%m-%d %H:%M:%S')}", footer_style))
        
        # Build PDF
        doc.build(story)
        print(f"{C.G}✅ Professional report generated: {filepath}{C.E}")
        return str(filepath)
    
    def _create_status_overview_box(self, health_results, healthy_count, basic_results, suspended_services):
        """Create a clean status overview box with updated data structure"""
        active_services = len(health_results) + len(basic_results)
        
        # Count healthy services from new data structure [Service, Status, DNS Info, Pods, Root Cause]
        healthy_services = 0
        for result in health_results:
            status = result[1]  # Status is now in second column
            if 'HEALTHY' in status or 'UP' in status:
                healthy_services += 1
                
        accessible_services = 0
        for result in basic_results:
            status = result[1]  # Status is now in second column
            if 'ACCESSIBLE' in status:
                accessible_services += 1
        
        total_healthy = healthy_services + accessible_services
        
        if active_services > 0:
            overall_health_rate = (total_healthy / active_services) * 100
        else:
            overall_health_rate = 0
        
        # Determine status and color
        if overall_health_rate >= 95:
            status = "EXCELLENT"
            status_color = colors.HexColor('#00A651')
        elif overall_health_rate >= 85:
            status = "HEALTHY" 
            status_color = colors.HexColor('#00A651')
        elif overall_health_rate >= 70:
            status = "DEGRADED"
            status_color = colors.HexColor('#FFB81C')
        else:
            status = "CRITICAL"
            status_color = colors.HexColor('#E20074')
        
        data = [
            ['SYSTEM STATUS', f'{status}', f'{overall_health_rate:.1f}%'],
            ['Active Endpoints', f'{total_healthy}/{active_services}', 'Operational'],
            ['Suspended Services', f'{len(suspended_services)}', 'Zero Pods']
        ]
        
        # Consistent column widths
        table = Table(data, colWidths=[2.5*inch, 2.5*inch, 2.5*inch])
        table.setStyle(TableStyle([
            # Header styling - consistent with other tables
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#E20074')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('BACKGROUND', (1, 0), (1, 0), status_color),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            
            # Consistent padding
            ('TOPPADDING', (0, 0), (-1, 0), 8),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
            ('TOPPADDING', (0, 1), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 4),
            ('LEFTPADDING', (0, 0), (-1, -1), 4),
            ('RIGHTPADDING', (0, 0), (-1, -1), 4),
            
            # Professional appearance
            ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#F8F8F8')),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CCCCCC')),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE')
        ]))
        
        return table
    
    def _create_tmobile_stats_table(self, health_results, healthy_count, basic_results,
                                  services_no_selector, services_no_health_probe,
                                  services_no_ingress, suspended_services):
        """Create T-Mobile styled statistics table with consistent formatting"""
        active_endpoints = len(health_results) + len(basic_results)
        
        # Count unique services from flat results
        unique_services = set()
        for result in health_results:
            service_name = result[0].split(' (')[0].replace('└─ ', '')  # Extract base service name
            unique_services.add(service_name)
        for result in basic_results:
            service_name = result[0].split(' (')[0].replace('└─ ', '')  # Extract base service name
            unique_services.add(service_name)
        
        total_services = (len(unique_services) + len(suspended_services) + 
                         len(services_no_selector) + len(services_no_health_probe) + 
                         len(services_no_ingress))
        
        accessible_count = sum(1 for r in basic_results if 'ACCESSIBLE' in r[1]) if basic_results else 0
        total_healthy = healthy_count + accessible_count
        
        data = [
            ['Metric', 'Count', '%'],
            ['Total Services', str(total_services), '100%'],
            ['Total Endpoints', str(active_endpoints), '-'],
            ['Active Services', str(len(unique_services)), f'{(len(unique_services)/total_services*100):.0f}%' if total_services > 0 else '0%'],
            ['Healthy Endpoints', str(total_healthy), f'{(total_healthy/active_endpoints*100):.0f}%' if active_endpoints > 0 else '0%'],
            ['Suspended Services', str(len(suspended_services)), f'{(len(suspended_services)/total_services*100):.0f}%' if total_services > 0 else '0%'],
            ['Missing Health Probes', str(len(services_no_health_probe)), f'{(len(services_no_health_probe)/total_services*100):.0f}%' if total_services > 0 else '0%'],
            ['Missing Ingress', str(len(services_no_ingress)), f'{(len(services_no_ingress)/total_services*100):.0f}%' if total_services > 0 else '0%'],
            ['Missing Selectors', str(len(services_no_selector)), f'{(len(services_no_selector)/total_services*100):.0f}%' if total_services > 0 else '0%']
        ]
        
        # Professional column widths
        table = Table(data, colWidths=[4.0*inch, 1.8*inch, 1.7*inch])
        table.setStyle(TableStyle([
            # Header styling - consistent with results table
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#E20074')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            
            # Content styling
            ('ALIGN', (0, 1), (0, -1), 'LEFT'),
            ('ALIGN', (1, 1), (-1, -1), 'CENTER'),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            
            # Consistent padding
            ('TOPPADDING', (0, 0), (-1, 0), 8),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
            ('TOPPADDING', (0, 1), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 4),
            ('LEFTPADDING', (0, 0), (-1, -1), 4),
            ('RIGHTPADDING', (0, 0), (-1, -1), 4),
            
            # Professional appearance
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.HexColor('#F8F8F8'), colors.white]),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CCCCCC')),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE')
        ]))
        
        return table
    
    def _create_tmobile_results_table(self, results):
        """Create T-Mobile styled results table with consistent professional formatting"""
        if not results:
            return None
        
        from reportlab.platypus import Paragraph
        styles = getSampleStyleSheet()
        
        # Consistent professional style for all content
        content_style = ParagraphStyle(
            'ContentStyle',
            parent=styles['Normal'],
            fontSize=8,
            textColor=colors.HexColor('#333333'),
            leftIndent=0,
            rightIndent=0,
            spaceAfter=1,
            spaceBefore=1,
            leading=9
        )
        
        # Style specifically for faulty pods with better spacing
        pod_style = ParagraphStyle(
            'PodStyle',
            parent=styles['Normal'],
            fontSize=7,
            textColor=colors.HexColor('#333333'),
            leftIndent=0,
            rightIndent=0,
            spaceAfter=0,
            spaceBefore=0,
            leading=8
        )
        
        # Process data with consistent formatting
        clean_data = [['Service Endpoint', 'Status', 'Pods', 'Root Cause Analysis']]
        
        for row in results:
            clean_row = []
            for i, cell in enumerate(row):
                # Remove ANSI color codes
                clean_cell = str(cell)
                clean_cell = re.sub(r'\033\[[0-9;]+m', '', clean_cell)
                
                if i == 0:  # Service name - use Paragraph for consistent formatting
                    wrapped_service = self._wrap_text(clean_cell, 18)
                    clean_cell = Paragraph(wrapped_service, content_style)
                elif i == 1:  # Status - use Paragraph for consistency
                    clean_cell = Paragraph(clean_cell, content_style)
                elif i == 2:  # Pod count - use Paragraph for consistency
                    clean_cell = Paragraph(clean_cell, content_style)
                elif i == 3:  # Root cause analysis - structured format
                    formatted_analysis = self._format_root_cause_for_pdf(clean_cell)
                    clean_cell = Paragraph(formatted_analysis, pod_style)
                
                clean_row.append(clean_cell)
            clean_data.append(clean_row)
        
        # Professional column widths - total = 7.5 inches
        table = Table(clean_data, colWidths=[1.8*inch, 1.0*inch, 0.6*inch, 4.1*inch])
        
        style_commands = [
            # Header styling
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#E20074')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            
            # Content alignment
            ('ALIGN', (0, 1), (0, -1), 'LEFT'),    # Service names left
            ('ALIGN', (1, 1), (1, -1), 'CENTER'),  # Status center
            ('ALIGN', (2, 1), (2, -1), 'CENTER'),  # Pod count center
            ('ALIGN', (3, 1), (3, -1), 'LEFT'),    # Root cause left
            
            # Consistent padding - reduced for professional look
            ('TOPPADDING', (0, 0), (-1, 0), 8),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
            ('TOPPADDING', (0, 1), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 4),
            ('LEFTPADDING', (0, 0), (-1, -1), 4),
            ('RIGHTPADDING', (0, 0), (-1, -1), 4),
            
            # Professional grid and background
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CCCCCC')),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.HexColor('#F8F8F8'), colors.white])
        ]
        
        # Status-based coloring with professional colors
        for i, row in enumerate(clean_data[1:], start=1):
            if hasattr(row[1], 'text'):  # Check if it's a Paragraph object
                status_text = row[1].text
            else:
                status_text = str(row[1])
                
            if 'UP' in status_text or 'ACCESSIBLE' in status_text:
                style_commands.append(('BACKGROUND', (1, i), (1, i), colors.HexColor('#E8F5E8')))
            elif 'DOWN' in status_text or 'ERROR' in status_text or 'TIMEOUT' in status_text or 'UNREACHABLE' in status_text:
                style_commands.append(('BACKGROUND', (1, i), (1, i), colors.HexColor('#FDE8E8')))
            else:
                style_commands.append(('BACKGROUND', (1, i), (1, i), colors.HexColor('#FFF8E1')))
        
        table.setStyle(TableStyle(style_commands))
        return table
    
    def _format_root_cause_for_pdf(self, analysis_text):
        """Format root cause analysis for PDF with consistent professional formatting"""
        if ':' not in analysis_text:
            return analysis_text
        
        parts = analysis_text.split(':', 1)
        count_part = parts[0]
        details_part = parts[1].strip()
        
        # Handle "0: None" case
        if details_part.lower() in ['none', ''] or count_part == '0':
            return f"<b>{count_part}:</b> None"
        
        # Split analysis details and format each on a separate line
        analysis_details = []
        if ';' in details_part:
            # Multiple pods with analysis
            for analysis_info in details_part.split(';'):
                analysis_info = analysis_info.strip()
                if analysis_info:
                    analysis_details.append(analysis_info)
        else:
            # Single pod or simple analysis
            analysis_details = [details_part]
        
        if not analysis_details:
            return f"<b>{count_part}:</b> None"
        
        # Create compact structured format
        formatted_result = f"<b>{count_part}:</b><br/>"
        formatted_result += "<br/>".join(f"• {detail}" for detail in analysis_details)
        
        return formatted_result
    
    def _create_tmobile_service_table(self, services):
        """Create clean T-Mobile styled service list table with consistent formatting"""
        if not services:
            return Paragraph("<i>No services in this category.</i>", getSampleStyleSheet()['Normal'])
        
        # Create data in columns of 3 for professional layout
        data = [['Service Name', 'Service Name', 'Service Name']]
        
        # Wrap service names professionally
        wrapped_services = [self._wrap_text(svc, 22) for svc in services]
        
        # Pad to make divisible by 3
        while len(wrapped_services) % 3 != 0:
            wrapped_services.append('')
        
        # Group into rows of 3
        for i in range(0, len(wrapped_services), 3):
            row = wrapped_services[i:i+3]
            data.append(row)
        
        # Professional column widths
        table = Table(data, colWidths=[2.5*inch, 2.5*inch, 2.5*inch])
        table.setStyle(TableStyle([
            # Header styling - consistent with other tables
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#E20074')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            
            # Consistent padding
            ('TOPPADDING', (0, 0), (-1, 0), 8),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
            ('TOPPADDING', (0, 1), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 4),
            ('LEFTPADDING', (0, 0), (-1, -1), 4),
            ('RIGHTPADDING', (0, 0), (-1, -1), 4),
            
            # Professional appearance
            ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#F8F8F8')),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CCCCCC')),
            ('VALIGN', (0, 0), (-1, -1), 'TOP')
        ]))
        
        return table

def get_previous_container_logs(v1, namespace, pod_name, container_name=None):
    """Get logs from previous container instance to understand restart loops"""
    try:
        if container_name:
            log_response = v1.read_namespaced_pod_log(
                name=pod_name,
                namespace=namespace,
                container=container_name,
                previous=True,
                tail_lines=100
            )
        else:
            log_response = v1.read_namespaced_pod_log(
                name=pod_name,
                namespace=namespace,
                previous=True,
                tail_lines=100
            )
        return log_response
    except Exception:
        return None

def extract_stack_trace(log_lines):
    """Extract meaningful stack trace information from logs"""
    stack_trace_lines = []
    in_stack_trace = False
    
    for line in log_lines:
        line_clean = line.strip()
        
        # Start of stack trace patterns
        if (re.search(r'(Exception|Error|Caused by|Traceback|Fatal)', line_clean, re.IGNORECASE) and 
            not in_stack_trace):
            in_stack_trace = True
            stack_trace_lines.append(line_clean)
            continue
            
        # Continue stack trace collection
        if in_stack_trace:
            # Stack trace continuation patterns
            if (re.match(r'\s*(at |Caused by|\t|\s+File |\s+line )', line_clean) or 
                'Exception' in line_clean or 'Error' in line_clean):
                stack_trace_lines.append(line_clean)
            else:
                # End of stack trace
                break
        
        # Single line errors without stack trace
        if re.search(r'(FATAL|CRITICAL|ERROR|EXCEPTION)', line_clean, re.IGNORECASE):
            return [line_clean]
    
    return stack_trace_lines

def analyze_pod_logs(v1, namespace, pod_name, container_name=None):
    """Enhanced intelligent log analysis to find exact root cause of failures"""
    try:
        # Get current container logs
        current_logs = None
        previous_logs = None
        
        try:
            if container_name:
                current_logs = v1.read_namespaced_pod_log(
                    name=pod_name,
                    namespace=namespace,
                    container=container_name,
                    tail_lines=100
                )
            else:
                current_logs = v1.read_namespaced_pod_log(
                    name=pod_name,
                    namespace=namespace,
                    tail_lines=100
                )
        except Exception as e:
            if "waiting to start" in str(e).lower():
                return "Container waiting to start - check image availability and resource limits"
        
        # Get previous container logs if available (for restart loop analysis)
        previous_logs = get_previous_container_logs(v1, namespace, pod_name, container_name)
        
        # Choose the best log source for analysis
        if previous_logs and len(previous_logs.strip()) > len(current_logs.strip() if current_logs else ""):
            log_response = previous_logs
            log_source = "previous"
        else:
            log_response = current_logs or ""
            log_source = "current"
        
        if not log_response or not log_response.strip():
            return "No logs available for analysis"
        
        log_lines = log_response.strip().split('\n')
        
        # Enhanced error patterns with more specific categorization
        error_patterns = {
            # Memory and Resource Issues
            'OutOfMemoryError': [
                r'java\.lang\.OutOfMemoryError.*',
                r'OutOfMemoryError.*',
                r'out of memory.*',
                r'Cannot allocate memory.*',
                r'killed.*memory.*',
                r'oom.*killed',
                r'memory.*exceeded'
            ],
            'Resource Limit Exceeded': [
                r'resource.*limit.*exceeded',
                r'cpu.*limit.*exceeded',
                r'memory.*limit.*exceeded',
                r'disk.*space.*exceeded',
                r'no space left on device'
            ],
            
            # Network and Connectivity Issues
            'Port Already in Use': [
                r'Port \d+ is already in use',
                r'Address already in use.*:\d+',
                r'bind.*address already in use',
                r'listen.*address already in use'
            ],
            'Database Connection Failed': [
                r'Connection refused.*:\d+',
                r'Unable to connect to database.*',
                r'Database connection failed.*',
                r'Connection timeout.*database',
                r'No route to host.*database',
                r'could not connect to server.*',
                r'connection.*refused.*sql',
                r'timeout.*connecting to database'
            ],
            'Service Discovery Failed': [
                r'service.*not found',
                r'unable to resolve.*service',
                r'dns.*resolution.*failed',
                r'service.*unreachable',
                r'no endpoints available'
            ],
            
            # Configuration Issues
            'Configuration Error': [
                r'Configuration.*error.*',
                r'Invalid configuration.*',
                r'Missing.*configuration.*',
                r'Unable to load config.*',
                r'config.*file.*not found',
                r'yaml.*parse.*error',
                r'json.*parse.*error',
                r'property.*not found'
            ],
            'Environment Variable Missing': [
                r'environment variable.*not set',
                r'required.*env.*var.*missing',
                r'undefined.*environment.*variable',
                r'missing.*required.*property'
            ],
            
            # Security and Permission Issues
            'Permission Denied': [
                r'Permission denied.*',
                r'Access denied.*',
                r'Forbidden.*403',
                r'insufficient.*permission.*',
                r'unauthorized.*401',
                r'authentication.*failed'
            ],
            'SSL/TLS Issues': [
                r'ssl.*handshake.*failed',
                r'certificate.*verification.*failed',
                r'tls.*handshake.*timeout',
                r'certificate.*expired'
            ],
            
            # File System Issues
            'File Not Found': [
                r'No such file or directory.*',
                r'FileNotFoundException.*',
                r'File not found.*',
                r'cannot open.*file',
                r'failed to read.*file'
            ],
            
            # Application Startup Issues
            'Application Startup Failed': [
                r'Application failed to start.*',
                r'Failed to start.*application',
                r'Startup.*failed.*',
                r'Unable to start.*server',
                r'Spring.*Application.*failed.*startup',
                r'main.*method.*failed'
            ],
            'Dependency Injection Failed': [
                r'dependency.*injection.*failed',
                r'bean.*creation.*failed',
                r'unable to create.*bean',
                r'circular.*dependency',
                r'bean.*not found'
            ],
            
            # Runtime Issues
            'Null Pointer Exception': [
                r'NullPointerException.*',
                r'null.*pointer.*exception',
                r'attempted.*null.*reference',
                r'dereferencing.*null'
            ],
            'Class Loading Issues': [
                r'ClassNotFoundException.*',
                r'NoClassDefFoundError.*',
                r'class.*not found.*',
                r'unable to load.*class'
            ],
            
            # Container and Image Issues
            'Image Pull Failed': [
                r'image.*pull.*failed',
                r'failed to pull.*image',
                r'image.*not found',
                r'registry.*unreachable'
            ],
            
            # Health Check Issues
            'Health Check Failed': [
                r'health.*check.*failed',
                r'readiness.*probe.*failed',
                r'liveness.*probe.*failed',
                r'probe.*timeout'
            ]
        }
        
        # Look for stack traces first (most informative)
        stack_trace = extract_stack_trace(log_lines)
        if stack_trace and len(stack_trace) > 1:
            # Found a meaningful stack trace
            root_error = stack_trace[0]  # The main error line
            
            # Extract the most relevant error information
            for error_type, patterns in error_patterns.items():
                for pattern in patterns:
                    if re.search(pattern, root_error, re.IGNORECASE):
                        # Get additional context from stack trace
                        if len(stack_trace) > 1:
                            context_lines = stack_trace[1:min(3, len(stack_trace))]
                            context = " | ".join([line.strip() for line in context_lines])
                            return f"🔍 {error_type}: {root_error} → {context} ({log_source} logs)"
                        else:
                            return f"🔍 {error_type}: {root_error} ({log_source} logs)"
            
            # If no specific pattern matched but we have a stack trace
            return f"🔍 Stack Trace Error: {root_error} ({log_source} logs)"
        
        # Look for specific error patterns in recent log lines
        recent_lines = log_lines[-30:]  # Check last 30 lines
        for log_line in reversed(recent_lines):
            log_line_clean = log_line.strip()
            if not log_line_clean:
                continue
                
            for error_type, patterns in error_patterns.items():
                for pattern in patterns:
                    match = re.search(pattern, log_line_clean, re.IGNORECASE)
                    if match:
                        # Extract more context around the error
                        line_index = log_lines.index(log_line)
                        
                        # Get surrounding context (1-2 lines before and after)
                        context_start = max(0, line_index - 2)
                        context_end = min(len(log_lines), line_index + 3)
                        context_lines = log_lines[context_start:context_end]
                        
                        # Clean up context and find the most relevant error information
                        error_context = []
                        for ctx_line in context_lines:
                            ctx_clean = ctx_line.strip()
                            if ctx_clean and ('error' in ctx_clean.lower() or 
                                           'exception' in ctx_clean.lower() or 
                                           'failed' in ctx_clean.lower() or
                                           'fatal' in ctx_clean.lower()):
                                # Truncate very long lines but preserve key information
                                if len(ctx_clean) > 120:
                                    # Find the error part and extract meaningful context
                                    error_start = max(0, ctx_clean.lower().find('error') - 10)
                                    if error_start == -10:  # 'error' not found, try 'exception'
                                        error_start = max(0, ctx_clean.lower().find('exception') - 10)
                                    if error_start == -10:  # neither found, try 'failed'
                                        error_start = max(0, ctx_clean.lower().find('failed') - 10)
                                    
                                    error_end = min(len(ctx_clean), error_start + 120)
                                    ctx_clean = "..." + ctx_clean[error_start:error_end] + "..."
                                
                                error_context.append(ctx_clean)
                        
                        # Format the result with exact error details
                        if error_context:
                            main_error = error_context[0]  # Primary error line
                            additional_context = " | ".join(error_context[1:2])  # Up to 1 additional line
                            
                            if additional_context:
                                return f"🔍 {error_type}: {main_error} → {additional_context} ({log_source} logs)"
                            else:
                                return f"🔍 {error_type}: {main_error} ({log_source} logs)"
                        else:
                            # Fallback to the matched line
                            if len(log_line_clean) > 120:
                                truncated_line = log_line_clean[:120] + "..."
                            else:
                                truncated_line = log_line_clean
                            return f"🔍 {error_type}: {truncated_line} ({log_source} logs)"
        
        # Enhanced general error detection with timestamp extraction
        for log_line in reversed(recent_lines):
            log_line_clean = log_line.strip()
            if any(keyword in log_line_clean.lower() for keyword in ['fatal', 'error', 'exception', 'failed']):
                # Extract timestamp if present
                timestamp_pattern = r'(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2})'
                timestamp_match = re.search(timestamp_pattern, log_line_clean)
                timestamp_info = f"at {timestamp_match.group(1)}" if timestamp_match else ""
                
                # Clean up and format the error line
                error_line = re.sub(timestamp_pattern, '', log_line_clean).strip()
                if len(error_line) > 150:
                    # Find the most important part of the error
                    error_keywords = ['error', 'exception', 'failed', 'fatal']
                    for keyword in error_keywords:
                        keyword_pos = error_line.lower().find(keyword)
                        if keyword_pos != -1:
                            start = max(0, keyword_pos - 20)
                            end = min(len(error_line), keyword_pos + 130)
                            error_line = "..." + error_line[start:end] + "..."
                            break
                    else:
                        error_line = error_line[:150] + "..."
                
                error_info = f"{error_line} {timestamp_info}".strip()
                return f"🔍 Critical Error: {error_info} ({log_source} logs)"
        
        # If no specific errors found, check for application-specific issues
        app_specific_checks = [
            # Spring Boot specific
            (r'Failed to configure a DataSource', 'Spring Boot: Database configuration missing'),
            (r'Web server failed to start', 'Spring Boot: Web server startup failed'),
            (r'APPLICATION FAILED TO START', 'Spring Boot: Application startup failure'),
            
            # Node.js specific  
            (r'Error: Cannot find module', 'Node.js: Missing module dependency'),
            (r'EADDRINUSE.*:\d+', 'Node.js: Port already in use'),
            (r'ECONNREFUSED.*:\d+', 'Node.js: Connection refused'),
            
            # Generic patterns
            (r'Exit code: (\d+)', 'Process exited with code {}'),
            (r'signal (\d+)', 'Process killed by signal {}')
        ]
        
        for pattern, description in app_specific_checks:
            for log_line in reversed(recent_lines):
                match = re.search(pattern, log_line, re.IGNORECASE)
                if match:
                    if '{}' in description:
                        formatted_desc = description.format(match.group(1))
                    else:
                        formatted_desc = description
                    
                    # Add context from the actual log line
                    context_line = log_line.strip()
                    if len(context_line) > 100:
                        context_line = context_line[:100] + "..."
                    
                    return f"🔍 {formatted_desc}: {context_line} ({log_source} logs)"
        
        # Last resort: return indication that logs were analyzed
        if log_lines:
            return f"🔍 Restart detected - no specific error pattern found in {len(log_lines)} log lines ({log_source} logs)"
        else:
            return "🔍 Restart detected - no logs available for analysis"
        
    except Exception as e:
        return f"🔍 Log analysis failed: {str(e)}"

def get_detailed_restart_loop_info(v1, namespace, pod, container):
    """Get comprehensive restart loop information including exact error details"""
    pod_name = pod.metadata.name
    container_name = container.name
    
    restart_info = {
        'restart_count': container.restart_count,
        'current_state': None,
        'last_termination': None,
        'exact_error': None,
        'exit_code': None,
        'restart_reason': None
    }
    
    # Analyze current container state
    if container.state:
        if container.state.waiting:
            restart_info['current_state'] = container.state.waiting.reason
            if container.state.waiting.message:
                restart_info['exact_error'] = container.state.waiting.message
        elif container.state.terminated:
            restart_info['current_state'] = 'Terminated'
            restart_info['exit_code'] = container.state.terminated.exit_code
            restart_info['restart_reason'] = container.state.terminated.reason
            if container.state.terminated.message:
                restart_info['exact_error'] = container.state.terminated.message
    
    # Get last termination state for additional details
    if container.last_state and container.last_state.terminated:
        term = container.last_state.terminated
        restart_info['last_termination'] = {
            'exit_code': term.exit_code,
            'reason': term.reason,
            'message': term.message,
            'finished_at': term.finished_at
        }
    
    # Get detailed log analysis for restart loops
    log_analysis = analyze_pod_logs(v1, namespace, pod_name, container_name)
    
    return restart_info, log_analysis

def analyze_pod_fault(pod, v1, namespace):
    """Enhanced pod fault analysis with detailed restart loop detection"""
    pod_name = pod.metadata.name
    reasons = []
    root_cause = None
    detailed_analyses = []
    
    # Check pod phase
    if pod.status.phase == 'Failed':
        reasons.append(f"Phase: {pod.status.phase}")
        if pod.status.message:
            reasons.append(f"Message: {pod.status.message}")
    elif pod.status.phase == 'Pending':
        reasons.append(f"Phase: {pod.status.phase}")
        if pod.status.conditions:
            for condition in pod.status.conditions:
                if condition.status == 'False' and condition.reason:
                    reasons.append(f"Condition: {condition.reason}")
    
    # Enhanced container state analysis
    if pod.status.container_statuses:
        for container in pod.status.container_statuses:
            container_name = container.name
            
            # Detailed restart loop analysis
            if (container.state and container.state.waiting and 
                container.state.waiting.reason == 'CrashLoopBackOff'):
                
                reasons.append(f"Container {container_name}: CrashLoopBackOff")
                
                # Get comprehensive restart loop information
                restart_info, log_analysis = get_detailed_restart_loop_info(v1, namespace, pod, container)
                
                # Build detailed analysis
                analysis_parts = []
                analysis_parts.append(f"Restart Count: {restart_info['restart_count']}")
                
                if restart_info['exit_code']:
                    analysis_parts.append(f"Exit Code: {restart_info['exit_code']}")
                
                if restart_info['restart_reason']:
                    analysis_parts.append(f"Termination Reason: {restart_info['restart_reason']}")
                
                if restart_info['exact_error']:
                    # Truncate very long error messages but preserve key info
                    exact_error = restart_info['exact_error']
                    if len(exact_error) > 200:
                        exact_error = exact_error[:200] + "..."
                    analysis_parts.append(f"Container Error: {exact_error}")
                
                # Add log analysis
                if log_analysis and "no specific error pattern found" not in log_analysis:
                    analysis_parts.append(f"Log Analysis: {log_analysis}")
                
                # Combine all analysis
                detailed_analysis = " | ".join(analysis_parts)
                detailed_analyses.append(f"{container_name} → {detailed_analysis}")
                
                root_cause = f"RESTART LOOP: {detailed_analysis}"
            
            # High restart count with current issues (potential restart loop)
            elif container.restart_count >= 3 and not container.ready:
                reasons.append(f"Container {container_name}: High restarts ({container.restart_count}), not ready")
                
                # Get detailed analysis for high restart scenarios
                restart_info, log_analysis = get_detailed_restart_loop_info(v1, namespace, pod, container)
                
                analysis_parts = [f"Restart Count: {restart_info['restart_count']}"]
                
                if restart_info['current_state']:
                    analysis_parts.append(f"State: {restart_info['current_state']}")
                
                if log_analysis and "no specific error pattern found" not in log_analysis:
                    analysis_parts.append(f"Log Analysis: {log_analysis}")
                
                detailed_analysis = " | ".join(analysis_parts)
                detailed_analyses.append(f"{container_name} → {detailed_analysis}")
                
                root_cause = f"HIGH RESTARTS: {detailed_analysis}"
            
            # Image pull errors with enhanced details
            elif (container.state and container.state.waiting and 
                  container.state.waiting.reason in ['ImagePullBackOff', 'ErrImagePull']):
                reasons.append(f"Container {container_name}: {container.state.waiting.reason}")
                
                error_message = container.state.waiting.message or "Image pull failed"
                if len(error_message) > 150:
                    error_message = error_message[:150] + "..."
                
                detailed_analyses.append(f"{container_name} → {error_message}")
                root_cause = f"IMAGE ERROR: {error_message}"
            
            # Config errors with enhanced details
            elif (container.state and container.state.waiting and 
                  container.state.waiting.reason == 'CreateContainerConfigError'):
                reasons.append(f"Container {container_name}: Config Error")
                
                error_message = container.state.waiting.message or "Configuration error"
                if len(error_message) > 150:
                    error_message = error_message[:150] + "..."
                
                detailed_analyses.append(f"{container_name} → {error_message}")
                root_cause = f"CONFIG ERROR: {error_message}"
            
            # Running but restarting containers
            elif container.restart_count > 0 and container.state and container.state.running:
                if container.restart_count >= 5:  # High restart count threshold
                    # Still get log analysis for frequently restarting containers
                    restart_info, log_analysis = get_detailed_restart_loop_info(v1, namespace, pod, container)
                    
                    if log_analysis and "no specific error pattern found" not in log_analysis:
                        analysis_parts = [f"Restart Count: {restart_info['restart_count']}", f"Analysis: {log_analysis}"]
                        detailed_analysis = " | ".join(analysis_parts)
                        detailed_analyses.append(f"{container_name} → {detailed_analysis}")
                        root_cause = f"FREQUENT RESTARTS: {detailed_analysis}"
    
    # Check pod conditions for additional insights
    if pod.status.conditions and not root_cause:
        for condition in pod.status.conditions:
            if condition.status == 'False' and condition.type in ['Ready', 'ContainersReady']:
                if condition.reason and condition.reason not in [r.split(':')[-1].strip() for r in reasons]:
                    reasons.append(f"{condition.type}: {condition.reason}")
                    if condition.message:
                        message = condition.message
                        if len(message) > 150:
                            message = message[:150] + "..."
                        root_cause = f"READINESS ISSUE: {message}"
    
    # Return enhanced analysis
    if detailed_analyses:
        # If we have detailed analyses, use the most comprehensive one
        return reasons, detailed_analyses[0]  # Return the first detailed analysis
    
    return reasons, root_cause

def get_pod_stats(pods, selector, v1, namespace):
    """Get enhanced pod statistics for a service with intelligent restart loop analysis"""
    matching_pods = [pod for pod in pods.items 
                    if all((pod.metadata.labels or {}).get(k) == v for k, v in selector.items())]
    
    total_pods = len(matching_pods)
    faulty_pod_details = []
    restart_loop_pods = []
    
    for pod in matching_pods:
        # Check for fault conditions with enhanced restart loop detection
        is_faulty = False
        is_restart_loop = False
        pod_name = pod.metadata.name
        
        # Basic fault checks
        if pod.status.phase in ['Failed', 'Pending']:
            is_faulty = True
        
        # Enhanced container state checks with restart loop focus
        if pod.status.container_statuses:
            for container in pod.status.container_statuses:
                container_name = container.name
                restart_count = container.restart_count
                
                # Detect restart loops with different severity levels
                if (container.state and container.state.waiting and 
                    container.state.waiting.reason == 'CrashLoopBackOff'):
                    is_faulty = True
                    is_restart_loop = True
                    restart_loop_pods.append(pod_name)
                
                # High restart count detection (potential restart loop)
                elif restart_count >= 3:
                    is_faulty = True
                    if restart_count >= 5:
                        is_restart_loop = True
                        restart_loop_pods.append(pod_name)
                
                # Image or config errors
                elif (container.state and container.state.waiting and 
                      container.state.waiting.reason in ['ImagePullBackOff', 'ErrImagePull', 'CreateContainerConfigError']):
                    is_faulty = True
        
        if is_faulty:
            # Get enhanced fault analysis with restart loop focus
            reasons, root_cause = analyze_pod_fault(pod, v1, namespace)
            
            # Enhanced detail formatting for restart loops
            if is_restart_loop:
                detail = f"🔄 RESTART LOOP - {pod_name}: {root_cause}" if root_cause else f"🔄 RESTART LOOP - {pod_name}: {'; '.join(reasons[:2])}"
            else:
                detail = f"{pod_name}: {root_cause}" if root_cause else f"{pod_name}: {'; '.join(reasons[:1])}"
            
            faulty_pod_details.append({
                'name': pod_name,
                'reasons': reasons,
                'root_cause': root_cause,
                'detail': detail,
                'is_restart_loop': is_restart_loop
            })
    
    return total_pods, faulty_pod_details, matching_pods, restart_loop_pods

def get_all_ingress_endpoints_for_service(ingresses, service_name):
    """Get ALL ingress endpoints for a specific service"""
    ingress_endpoints = []
    
    for ingress in ingresses.items:
        if ingress.spec.rules:
            for rule in ingress.spec.rules:
                if rule.host and rule.http and rule.http.paths:
                    for path in rule.http.paths:
                        if path.backend.service and path.backend.service.name == service_name:
                            endpoint = f"https://{rule.host}"
                            if endpoint not in ingress_endpoints:
                                ingress_endpoints.append(endpoint)
    
    return ingress_endpoints

def get_health_check_endpoints(namespace):
    config.load_kube_config()
    v1, networking_v1 = client.CoreV1Api(), client.NetworkingV1Api()
    
    services = v1.list_namespaced_service(namespace)
    pods = v1.list_namespaced_pod(namespace)
    ingresses = networking_v1.list_namespaced_ingress(namespace)
    
    health_endpoints = []
    basic_endpoints = []
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
        
        # Get enhanced pod statistics with restart loop detection
        total_pods, faulty_pod_details, matching_pods, restart_loop_pods = get_pod_stats(pods, selector, v1, namespace)
        
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
        
        # Find ALL ingress endpoints for this service
        ingress_endpoints = get_all_ingress_endpoints_for_service(ingresses, svc_name)
        
        if health_path and ingress_endpoints:
            # Service has both health probe and ingress(es) - consolidate into single entry
            health_endpoints.append({
                'service': svc_name,
                'base_service': svc_name,
                'endpoints': ingress_endpoints,  # Store all endpoints
                'health_path': health_path,
                'total_pods': total_pods,
                'faulty_pod_details': faulty_pod_details,
                'restart_loop_pods': restart_loop_pods
            })
                
        elif ingress_endpoints and not health_path:
            # Service has ingress(es) but no health probe - consolidate into single entry
            basic_endpoints.append({
                'service': svc_name,
                'base_service': svc_name,
                'endpoints': ingress_endpoints,  # Store all endpoints
                'total_pods': total_pods,
                'faulty_pod_details': faulty_pod_details,
                'restart_loop_pods': restart_loop_pods
            })
                
        elif health_path and not ingress_endpoints:
            # Service has health probe but no ingress
            services_no_ingress.append(svc_name)
        else:
            # Service has no health probe and no ingress
            services_no_health_probe.append(svc_name)
    
    return (health_endpoints, basic_endpoints, services_no_selector, 
            services_no_health_probe, services_no_ingress, suspended_services)

def format_root_cause_display(faulty_pod_details, service_is_healthy=False):
    """Enhanced formatting for console display with conditional restart loop indicators"""
    if not faulty_pod_details:
        return f"{C.G}0: None{C.E}"
    
    fault_count = len(faulty_pod_details)
    restart_loop_count = sum(1 for pod in faulty_pod_details if pod.get('is_restart_loop', False))
    
    # If service is healthy, only show restart counts, not detailed error analysis
    if service_is_healthy:
        if restart_loop_count > 0:
            display_text = f"{C.Y}{fault_count} pods with restarts ({restart_loop_count} restart loops) - Service UP{C.E}"
        elif fault_count > 0:
            display_text = f"{C.Y}{fault_count} pods with restarts - Service UP{C.E}"
        else:
            display_text = f"{C.G}0: None{C.E}"
        return display_text
    
    # Service is not healthy - show detailed analysis (existing logic)
    restart_loop_details = [pod for pod in faulty_pod_details if pod.get('is_restart_loop', False)]
    other_details = [pod for pod in faulty_pod_details if not pod.get('is_restart_loop', False)]
    
    display_parts = []
    
    # Show restart loops first (most critical)
    for pod_detail in restart_loop_details[:2]:
        root_cause = pod_detail.get('root_cause', 'Unknown restart issue')
        pod_name = pod_detail['name']
        
        if len(root_cause) > 80:
            if '🔍' in root_cause:
                key_part = root_cause.split('🔍')[1].strip()
                if ':' in key_part:
                    error_type = key_part.split(':')[0].strip()
                    short_cause = f"🔄 {error_type}"
                else:
                    short_cause = f"🔄 {key_part[:60]}..."
            else:
                short_cause = f"🔄 {root_cause[:60]}..."
        else:
            short_cause = f"🔄 {root_cause}"
        
        display_parts.append(f"{pod_name} → {short_cause}")
    
    # Show other faults if space allows
    remaining_space = 2 - len(restart_loop_details)
    for pod_detail in other_details[:remaining_space]:
        root_cause = pod_detail.get('root_cause', 'Unknown issue')
        pod_name = pod_detail['name']
        
        if len(root_cause) > 60:
            short_cause = root_cause[:60] + "..."
        else:
            short_cause = root_cause
        
        display_parts.append(f"{pod_name} → {short_cause}")
    
    # Format final display with restart loop emphasis
    if len(display_parts) > 2:
        shown = display_parts[:2]
        remaining = len(display_parts) - 2
        if restart_loop_count > 0:
            display_text = f"{C.R}{fault_count} ({restart_loop_count} restart loops): {'; '.join(shown)}... (+{remaining} more){C.E}"
        else:
            display_text = f"{C.R}{fault_count}: {'; '.join(shown)}... (+{remaining} more){C.E}"
    else:
        if restart_loop_count > 0:
            display_text = f"{C.R}{fault_count} ({restart_loop_count} restart loops): {'; '.join(display_parts)}{C.E}"
        else:
            display_text = f"{C.R}{fault_count}: {'; '.join(display_parts)}{C.E}"
    
    return display_text

def format_root_cause_for_pdf(faulty_pod_details, service_is_healthy=False):
    """Enhanced formatting for PDF with conditional detailed restart loop information"""
    if not faulty_pod_details:
        return "0: None"
    
    fault_count = len(faulty_pod_details)
    restart_loop_count = sum(1 for pod in faulty_pod_details if pod.get('is_restart_loop', False))
    
    # If service is healthy, only show summary information
    if service_is_healthy:
        if restart_loop_count > 0:
            return f"{fault_count} pods with restarts ({restart_loop_count} restart loops) - Service operational"
        elif fault_count > 0:
            return f"{fault_count} pods with previous restarts - Service operational"
        else:
            return "0: None"
    
    # Service is not healthy - show detailed analysis (existing logic)
    display_parts = []
    
    for pod_detail in faulty_pod_details:
        pod_name = pod_detail['name']
        root_cause = pod_detail.get('root_cause', 'Unknown issue')
        is_restart_loop = pod_detail.get('is_restart_loop', False)
        
        if root_cause:
            if is_restart_loop:
                display_parts.append(f"🔄 {pod_name} → {root_cause}")
            else:
                display_parts.append(f"{pod_name} → {root_cause}")
        else:
            reasons = pod_detail.get('reasons', [])
            if reasons:
                display_parts.append(f"{pod_name} → {'; '.join(reasons[:2])}")
            else:
                display_parts.append(pod_name)
    
    # Add restart loop summary if present
    if restart_loop_count > 0:
        return f"{fault_count} ({restart_loop_count} restart loops): " + '; '.join(display_parts)
    else:
        return f"{fault_count}: " + '; '.join(display_parts)

def check_health_endpoints(endpoints, namespace):
    """Check health endpoints with consolidated multi-DNS display"""
    if not endpoints:
        return [], 0
    
    print(f"\n{C.B}{C.C}🏥 Health Check: {namespace} ({len(endpoints)} services){C.E}")
    print(f"{C.C}{'─' * 70}{C.E}")
    
    results = []
    healthy_count = 0
    
    for i, ep in enumerate(endpoints, 1):
        service_name = ep['service']
        all_endpoints = ep['endpoints']
        health_path = ep['health_path']
        total_pods = ep['total_pods']
        faulty_pod_details = ep['faulty_pod_details']
        restart_loop_pods = ep.get('restart_loop_pods', [])
        
        # Display service name with endpoint count if multiple
        if len(all_endpoints) > 1:
            display_name = f"{service_name} ({len(all_endpoints)} DNS)"
            print(f"[{i}/{len(endpoints)}] {display_name:<25}", end=' ')
        else:
            print(f"[{i}/{len(endpoints)}] {service_name:<25}", end=' ')
        
        # Test all endpoints and consolidate results
        endpoint_results = []
        service_is_healthy = True
        
        for endpoint_url in all_endpoints:
            full_health_url = f"{endpoint_url}{health_path}"
            
            try:
                response = requests.get(full_health_url, timeout=8, verify=False, headers={'Accept': 'application/json'})
                
                # Check if service is reachable based on response content
                is_service_reachable = False
                response_indicators = []
                
                try:
                    response_text = response.text
                    response_text_lower = response_text.lower()
                    
                    # Spring Boot detection patterns
                    spring_boot_patterns = [
                        "whitelabel error page", "whitelabel", "this application has no explicit mapping",
                        "spring boot", "no message available", "type=not found, status=404"
                    ]
                    
                    for pattern in spring_boot_patterns:
                        if pattern in response_text_lower:
                            is_service_reachable = True
                            response_indicators.append("Spring Boot")
                            break
                    
                    if not is_service_reachable and len(response_text.strip()) > 50:
                        is_service_reachable = True
                        response_indicators.append("Service Response")
                        
                except Exception:
                    response_text = ""
                
                if response.status_code == 200:
                    try:
                        health_data = response.json()
                        
                        if 'status' in health_data:
                            status = health_data.get('status', 'UNKNOWN')
                        elif 'pong' in health_data:
                            pong_value = health_data.get('pong')
                            status = 'UP' if (pong_value is True or str(pong_value).lower() == 'true') else 'DOWN'
                        else:
                            status = 'UP'
                        
                    except json.JSONDecodeError:
                        status = 'UP'
                    
                    if status == 'UP':
                        endpoint_results.append('UP')
                    else:
                        endpoint_results.append(status)
                        service_is_healthy = False
                        
                elif response.status_code == 404 and is_service_reachable:
                    endpoint_results.append('UP')
                    
                elif response.status_code in [401, 403] and is_service_reachable:
                    endpoint_results.append('UP (Auth)')
                    
                else:
                    endpoint_results.append(f'HTTP {response.status_code}')
                    service_is_healthy = False
                
            except requests.exceptions.Timeout:
                endpoint_results.append('TIMEOUT')
                service_is_healthy = False
            except requests.exceptions.ConnectionError:
                endpoint_results.append('UNREACHABLE')
                service_is_healthy = False
            except Exception as e:
                endpoint_results.append(f'ERROR')
                service_is_healthy = False
        
        # Consolidate results across all endpoints
        unique_statuses = list(set(endpoint_results))
        up_count = sum(1 for status in endpoint_results if 'UP' in status)
        total_endpoints = len(endpoint_results)
        
        if up_count == total_endpoints:
            print(f"{C.G}✅ ALL UP ({total_endpoints}/{total_endpoints}){C.E}")
            consolidated_status = '🟢 ALL UP'
            healthy_count += 1
        elif up_count > 0:
            print(f"{C.Y}⚠️  PARTIAL ({up_count}/{total_endpoints} UP){C.E}")
            consolidated_status = f'🟡 PARTIAL ({up_count}/{total_endpoints})'
            service_is_healthy = False
        else:
            # All endpoints failed - show the most common failure
            failure_counts = {}
            for status in endpoint_results:
                failure_counts[status] = failure_counts.get(status, 0) + 1
            most_common_failure = max(failure_counts.keys(), key=lambda k: failure_counts[k])
            print(f"{C.R}❌ ALL DOWN ({most_common_failure}){C.E}")
            consolidated_status = f'🔴 ALL DOWN'
            service_is_healthy = False
        
        # Show DNS details if multiple endpoints and verbose or issues
        if len(all_endpoints) > 1 and (not service_is_healthy or up_count < total_endpoints):
            print(f"\n    DNS Details:")
            for j, (endpoint_url, status) in enumerate(zip(all_endpoints, endpoint_results)):
                dns_host = endpoint_url.replace('https://', '')
                status_color = C.G if 'UP' in status else C.R
                print(f"    [{j+1}] {dns_host:<30} {status_color}{status}{C.E}")
        
        # Use conditional formatting based on service health
        root_cause_display_pdf = format_root_cause_for_pdf(faulty_pod_details, service_is_healthy)
        
        # Create consolidated DNS info for PDF
        if len(all_endpoints) > 1:
            dns_info = f" | DNS: {', '.join([url.replace('https://', '') for url in all_endpoints])}"
            service_display_name = f"{service_name} ({len(all_endpoints)} endpoints)"
        else:
            dns_info = ""
            service_display_name = service_name
        
        results.append([service_display_name, consolidated_status, str(total_pods), root_cause_display_pdf + dns_info])
        
        # Show restart loop analysis only if service is not healthy
        if not service_is_healthy and restart_loop_pods:
            print(f"\n    🔄 RESTART LOOPS DETECTED: {len(restart_loop_pods)} pods")
            for pod_detail in faulty_pod_details:
                if pod_detail.get('is_restart_loop', False):
                    pod_name = pod_detail['name']
                    root_cause = pod_detail.get('root_cause', 'Unknown restart issue')
                    print(f"    └─ 🔍 {pod_name}: {root_cause}")
        elif service_is_healthy and (faulty_pod_details or restart_loop_pods):
            restart_loop_count = len(restart_loop_pods) if restart_loop_pods else 0
            if restart_loop_count > 0:
                print(f"    ℹ️  Service recovered - had {restart_loop_count} restart loop(s)")
            elif faulty_pod_details:
                print(f"    ℹ️  Service recovered - had pod restarts")
        elif not service_is_healthy and faulty_pod_details:
            for pod_detail in faulty_pod_details[:1]:
                root_cause = pod_detail.get('root_cause')
                if root_cause:
                    print(f"    └─ 🔍 {pod_detail['name']}: {root_cause}")
    
    return results, healthy_count

def check_basic_connectivity(basic_endpoints, namespace):
    """Check basic connectivity with consolidated multi-DNS display"""
    if not basic_endpoints:
        return []
    
    print(f"\n{C.B}{C.C}🌐 Basic Connectivity Check: {namespace} ({len(basic_endpoints)} services){C.E}")
    print(f"{C.C}{'─' * 70}{C.E}")
    
    results = []
    
    for i, ep in enumerate(basic_endpoints, 1):
        service_name = ep['service']
        all_endpoints = ep['endpoints']
        total_pods = ep['total_pods']
        faulty_pod_details = ep['faulty_pod_details']
        restart_loop_pods = ep.get('restart_loop_pods', [])
        
        # Display service name with endpoint count if multiple
        if len(all_endpoints) > 1:
            display_name = f"{service_name} ({len(all_endpoints)} DNS)"
            print(f"[{i}/{len(basic_endpoints)}] {display_name:<25}", end=' ')
        else:
            print(f"[{i}/{len(basic_endpoints)}] {service_name:<25}", end=' ')
        
        # Test all endpoints and consolidate results
        endpoint_results = []
        service_is_healthy = True
        
        for endpoint_url in all_endpoints:
            try:
                response = requests.get(endpoint_url, timeout=5, verify=False, allow_redirects=True)
                
                # Check if service is reachable
                is_service_reachable = False
                response_indicators = []
                
                try:
                    response_text = response.text.lower()
                    service_patterns = [
                        "whitelabel error page", "whitelabel", "this application has no explicit mapping",
                        "spring boot", "cannot get", "express", "<!doctype html>", "<html",
                        "nginx", "apache", "error 404", "not found"
                    ]
                    
                    for pattern in service_patterns:
                        if pattern in response_text:
                            is_service_reachable = True
                            if "spring" in pattern or "whitelabel" in pattern:
                                response_indicators.append("Spring Boot")
                            elif "cannot get" in pattern:
                                response_indicators.append("Node.js")
                            break
                    
                    if not is_service_reachable and len(response_text.strip()) > 20:
                        is_service_reachable = True
                        
                except Exception:
                    pass
                
                if response.status_code == 200:
                    endpoint_results.append('ACCESSIBLE')
                elif response.status_code in [301, 302]:
                    endpoint_results.append('ACCESSIBLE')
                elif response.status_code == 404 and is_service_reachable:
                    endpoint_results.append('ACCESSIBLE')
                elif response.status_code in [401, 403]:
                    endpoint_results.append('ACCESSIBLE (Auth)')
                else:
                    endpoint_results.append(f'HTTP {response.status_code}')
                    service_is_healthy = False
                
            except requests.exceptions.Timeout:
                endpoint_results.append('TIMEOUT')
                service_is_healthy = False
            except requests.exceptions.ConnectionError:
                endpoint_results.append('UNREACHABLE')
                service_is_healthy = False
            except Exception:
                endpoint_results.append('ERROR')
                service_is_healthy = False
        
        # Consolidate results
        accessible_count = sum(1 for status in endpoint_results if 'ACCESSIBLE' in status)
        total_endpoints = len(endpoint_results)
        
        if accessible_count == total_endpoints:
            print(f"{C.G}✅ ALL ACCESSIBLE ({total_endpoints}/{total_endpoints}){C.E}")
            consolidated_status = '🟢 ALL ACCESSIBLE'
        elif accessible_count > 0:
            print(f"{C.Y}⚠️  PARTIAL ({accessible_count}/{total_endpoints} UP){C.E}")
            consolidated_status = f'🟡 PARTIAL ({accessible_count}/{total_endpoints})'
            service_is_healthy = False
        else:
            failure_counts = {}
            for status in endpoint_results:
                failure_counts[status] = failure_counts.get(status, 0) + 1
            most_common_failure = max(failure_counts.keys(), key=lambda k: failure_counts[k])
            print(f"{C.R}❌ ALL DOWN ({most_common_failure}){C.E}")
            consolidated_status = f'🔴 ALL DOWN'
            service_is_healthy = False
        
        # Show DNS details if multiple endpoints and issues
        if len(all_endpoints) > 1 and (not service_is_healthy or accessible_count < total_endpoints):
            print(f"\n    DNS Details:")
            for j, (endpoint_url, status) in enumerate(zip(all_endpoints, endpoint_results)):
                dns_host = endpoint_url.replace('https://', '')
                status_color = C.G if 'ACCESSIBLE' in status else C.R
                print(f"    [{j+1}] {dns_host:<30} {status_color}{status}{C.E}")
        
        # Format root cause display for PDF
        root_cause_display = format_root_cause_for_pdf(faulty_pod_details, service_is_healthy)
        
        # Create detailed DNS info for PDF with individual status
        if len(all_endpoints) > 1:
            # Format DNS with individual status for PDF display
            dns_details = []
            for endpoint_url, status in zip(all_endpoints, endpoint_results):
                dns_host = endpoint_url.replace('https://', '')
                status_icon = "✅" if 'ACCESSIBLE' in status else "❌"
                dns_details.append(f"{status_icon} {dns_host}: {status}")
            
            # Create multi-line service display with detailed DNS status
            service_display_name = f"{service_name}\n" + "\n".join(dns_details)
            dns_info = ""  # Don't duplicate in root cause column
        else:
            dns_info = ""
            service_display_name = service_name
        
        results.append([service_display_name, consolidated_status, str(total_pods), root_cause_display + dns_info])
        
        # Show restart analysis conditionally
        if not service_is_healthy and restart_loop_pods:
            print(f"\n    🔄 RESTART LOOPS DETECTED: {len(restart_loop_pods)} pods")
        elif service_is_healthy and restart_loop_pods:
            print(f"    ℹ️  Service recovered - had {len(restart_loop_pods)} restart loop(s)")
    
    return results

def print_results(health_results, healthy_count, basic_results, services_no_selector, services_no_health_probe, services_no_ingress, suspended_services):
    # Calculate overall health excluding suspended services
    active_endpoints = len(health_results) + len(basic_results)
    
    # Count accessible services from basic connectivity
    accessible_count = sum(1 for r in basic_results if 'ACCESSIBLE' in r[1]) if basic_results else 0
    total_healthy = healthy_count + accessible_count
    
    # Health check results with clean table
    if health_results:
        total_endpoints = len(health_results)
        success_rate = (healthy_count/total_endpoints)*100
        
        print(f"\n{C.B}📊 HEALTH CHECK SUMMARY{C.E}")
        print(f"{C.C}{'=' * 90}{C.E}")
        print(tabulate(health_results, 
                      headers=['Service', 'Status', 'DNS Info', 'Pods', 'Root Cause Analysis'], 
                      tablefmt='simple',
                      colalign=['left', 'center', 'left', 'center', 'left']))
        
        print(f"\n{C.B}Health Stats:{C.E} {C.G}{healthy_count}/{total_endpoints} services healthy{C.E} ({success_rate:.0f}%)")
    
    # Basic connectivity results with clean table
    if basic_results:
        print(f"\n{C.B}🌐 CONNECTIVITY SUMMARY{C.E}")
        print(f"{C.C}{'=' * 90}{C.E}")
        print(tabulate(basic_results, 
                      headers=['Service', 'Status', 'DNS Info', 'Pods', 'Root Cause Analysis'], 
                      tablefmt='simple',
                      colalign=['left', 'center', 'left', 'center', 'left']))
        
        basic_success_rate = (accessible_count/len(basic_results))*100
        print(f"\n{C.B}Connectivity Stats:{C.E} {C.G}{accessible_count}/{len(basic_results)} services accessible{C.E} ({basic_success_rate:.0f}%)")
    
    # Overall system health (excluding suspended services)
    if active_endpoints > 0:
        overall_health_rate = (total_healthy / active_endpoints) * 100
        
        print(f"\n{C.B}🎯 SYSTEM OVERVIEW{C.E}")
        print(f"{C.C}{'=' * 90}{C.E}")
        print(f"{C.B}Overall Health:{C.E} {C.G}{total_healthy}/{active_endpoints} services operational{C.E} ({overall_health_rate:.1f}%)")
        
        # Show breakdown for clarity
        if health_results and basic_results:
            print(f"  • Health monitored: {healthy_count}/{len(health_results)} services")
            print(f"  • Basic connectivity: {accessible_count}/{len(basic_results)} services")
        
        # Count unique services for context
        unique_services = set()
        for result in health_results:
            service_name = result[0].split(' (')[0]
            unique_services.add(service_name)
        for result in basic_results:
            service_name = result[0].split(' (')[0]
            unique_services.add(service_name)
        
        print(f"  • Total active services: {len(unique_services)}")
        if len(suspended_services) > 0:
            print(f"  • Suspended services: {len(suspended_services)} (excluded from health calculation)")
    
    # Service categories with better organization
    if any([suspended_services, services_no_selector, services_no_health_probe, services_no_ingress]):
        print(f"\n{C.B}📋 SERVICE CATEGORIES{C.E}")
        print(f"{C.C}{'=' * 90}{C.E}")
        
        categories = [
            ("🛑 SUSPENDED SERVICES", suspended_services, "Services with zero pods", C.R),
            ("🔸 MISSING SELECTORS", services_no_selector, "Invalid service configuration", C.Y),
            ("🔸 MISSING HEALTH PROBES", services_no_health_probe, "No health monitoring configured", C.Y),
            ("🔸 MISSING INGRESS", services_no_ingress, "No external access configured", C.Y)
        ]
        
        for title, services, description, color in categories:
            if services:
                print(f"\n{color}{title} ({len(services)}){C.E} - {description}")
                # Display in columns for better readability
                if len(services) <= 5:
                    for svc in services:
                        print(f"  • {svc}")
                else:
                    # Show first few and indicate more
                    for svc in services[:5]:
                        print(f"  • {svc}")
                    if len(services) > 5:
                        print(f"  • ... and {len(services) - 5} more services")
    
    # Overall system status with clear indicators
    if active_endpoints > 0:
        print(f"\n{C.B}🏁 SYSTEM STATUS{C.E}")
        print(f"{C.C}{'=' * 90}{C.E}")
        
        if overall_health_rate >= 95:
            print(f"{C.G}🎉 EXCELLENT - System operating at peak performance{C.E}")
        elif overall_health_rate >= 85:
            print(f"{C.G}✅ HEALTHY - System operating normally{C.E}")
        elif overall_health_rate >= 70:
            print(f"{C.Y}⚠️  DEGRADED - Some services experiencing issues{C.E}")
        else:
            print(f"{C.R}🚨 CRITICAL - Multiple service failures detected{C.E}")
            
        # Add actionable recommendations
        if overall_health_rate < 85:
            print(f"\n{C.B}💡 RECOMMENDATIONS:{C.E}")
            if len(suspended_services) > 0:
                print(f"  • Investigate {len(suspended_services)} suspended services")
            if total_healthy < active_endpoints:
                failing_services = active_endpoints - total_healthy
                print(f"  • Address {failing_services} failing service endpoints")
            if len(services_no_health_probe) > 0:
                print(f"  • Add health probes to {len(services_no_health_probe)} services for better monitoring")
    else:
        print(f"\n{C.Y}⚠️  NO ACTIVE SERVICES - No services available for monitoring{C.E}")


def print_restart_loop_summary(namespace):
    """Print a comprehensive summary of all restart loops in the namespace"""
    try:
        config.load_kube_config()
        v1 = client.CoreV1Api()
        pods = v1.list_namespaced_pod(namespace)
        
        restart_loop_summary = []
        high_restart_pods = []
        
        for pod in pods.items:
            if pod.status.container_statuses:
                for container in pod.status.container_statuses:
                    restart_count = container.restart_count
                    container_name = container.name
                    pod_name = pod.metadata.name
                    
                    # Detect restart loops
                    is_crash_loop = (container.state and container.state.waiting and 
                                   container.state.waiting.reason == 'CrashLoopBackOff')
                    
                    if is_crash_loop or restart_count >= 5:
                        # Get detailed analysis
                        restart_info, log_analysis = get_detailed_restart_loop_info(v1, namespace, pod, container)
                        
                        summary_entry = {
                            'pod_name': pod_name,
                            'container_name': container_name,
                            'restart_count': restart_count,
                            'current_state': restart_info.get('current_state', 'Unknown'),
                            'exit_code': restart_info.get('exit_code'),
                            'log_analysis': log_analysis,
                            'is_crash_loop': is_crash_loop
                        }
                        
                        if is_crash_loop:
                            restart_loop_summary.append(summary_entry)
                        else:
                            high_restart_pods.append(summary_entry)
        
        # Display comprehensive restart loop information
        if restart_loop_summary or high_restart_pods:
            print(f"\n{C.B}{C.R}🔄 RESTART LOOP ANALYSIS - {namespace.upper()}{C.E}")
            print(f"{C.R}{'═' * 80}{C.E}")
            
            if restart_loop_summary:
                print(f"\n{C.R}🚨 CRASH LOOP BACKOFF PODS:{C.E}")
                for entry in restart_loop_summary:
                    print(f"\n{C.B}Pod:{C.E} {entry['pod_name']} | {C.B}Container:{C.E} {entry['container_name']}")
                    print(f"{C.B}Restart Count:{C.E} {entry['restart_count']} | {C.B}State:{C.E} {entry['current_state']}")
                    if entry['exit_code']:
                        print(f"{C.B}Exit Code:{C.E} {entry['exit_code']}")
                    print(f"{C.B}Root Cause:{C.E} {entry['log_analysis']}")
                    print(f"{C.C}{'─' * 60}{C.E}")
            
            if high_restart_pods:
                print(f"\n{C.Y}⚠️  HIGH RESTART COUNT PODS:{C.E}")
                for entry in high_restart_pods:
                    print(f"\n{C.B}Pod:{C.E} {entry['pod_name']} | {C.B}Container:{C.E} {entry['container_name']}")
                    print(f"{C.B}Restart Count:{C.E} {entry['restart_count']} | {C.B}State:{C.E} {entry['current_state']}")
                    if entry['log_analysis']:
                        print(f"{C.B}Analysis:{C.E} {entry['log_analysis']}")
                    print(f"{C.C}{'─' * 40}{C.E}")
        
    except Exception as e:
        print(f"{C.R}❌ Failed to analyze restart loops: {str(e)}{C.E}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="K8s health check monitor with intelligent restart loop analysis and consolidated multi-DNS support")
    parser.add_argument("namespace", help="Kubernetes namespace")
    parser.add_argument("--output-format", choices=['console', 'pdf', 'both'], 
                       default='console', help="Output format (default: console)")
    parser.add_argument("--output-dir", default="reports", 
                       help="Directory for reports (default: reports)")
    parser.add_argument("--verbose", "-v", action="store_true",
                       help="Show detailed fault analysis for all pods")
    parser.add_argument("--restart-analysis", "-r", action="store_true",
                       help="Show comprehensive restart loop analysis summary")
    args = parser.parse_args()
    
    try:
        (health_endpoints, basic_endpoints, services_no_selector, 
         services_no_health_probe, services_no_ingress, suspended_services) = get_health_check_endpoints(args.namespace)
        
        # Check health endpoints with consolidated display
        health_results, healthy_count = check_health_endpoints(health_endpoints, args.namespace)
        
        # Check basic connectivity with consolidated display
        basic_results = check_basic_connectivity(basic_endpoints, args.namespace)
        
        # Console output
        if args.output_format in ['console', 'both']:
            print_results(health_results, healthy_count, basic_results, 
                         services_no_selector, services_no_health_probe, 
                         services_no_ingress, suspended_services)
        
        # Comprehensive restart loop analysis if requested
        if args.restart_analysis:
            print_restart_loop_summary(args.namespace)
        
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
