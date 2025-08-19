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
        """Create a clean status overview box with enhanced service up detection"""
        active_services = len(health_results) + len(basic_results)
        
        # Count accessible services (including those showing Whitelabel Error Page or other UP indicators)
        accessible_count = 0
        if basic_results:
            for result in basic_results:
                status = result[1]
                # Count as accessible if status contains ACCESSIBLE, UP, or Whitelabel
                if any(keyword in status for keyword in ['ACCESSIBLE', 'UP', 'Whitelabel']):
                    accessible_count += 1
        
        total_healthy = healthy_count + accessible_count
        
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
            ['Active Services', f'{total_healthy}/{active_services}', 'Operational'],
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
        """Create T-Mobile styled statistics table with enhanced service up detection"""
        active_services = len(health_results) + len(basic_results)
        total_services = (active_services + len(suspended_services) + 
                         len(services_no_selector) + len(services_no_health_probe) + 
                         len(services_no_ingress))
        
        # Count accessible services (including those showing Whitelabel Error Page or other UP indicators)
        accessible_count = 0
        if basic_results:
            for result in basic_results:
                status = result[1]
                # Count as accessible if status contains ACCESSIBLE, UP, or Whitelabel
                if any(keyword in status for keyword in ['ACCESSIBLE', 'UP', 'Whitelabel']):
                    accessible_count += 1
        
        total_healthy = healthy_count + accessible_count
        
        data = [
            ['Metric', 'Count', '%'],
            ['Total Services', str(total_services), '100%'],
            ['Active Services', str(active_services), f'{(active_services/total_services*100):.0f}%' if total_services > 0 else '0%'],
            ['Healthy Services', str(total_healthy), f'{(total_healthy/active_services*100):.0f}%' if active_services > 0 else '0%'],
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
        clean_data = [['Service', 'Status', 'Pods', 'Root Cause Analysis']]
        
        for row in results:
            clean_row = []
            for i, cell in enumerate(row):
                # Remove ANSI color codes
                clean_cell = str(cell)
                clean_cell = re.sub(r'\033\[[0-9;]+m', '', clean_cell)
                
                if i == 0:  # Service name - use Paragraph for consistent formatting
                    wrapped_service = self._wrap_text(clean_cell, 15)
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
        table = Table(clean_data, colWidths=[1.5*inch, 1.0*inch, 0.6*inch, 4.4*inch])
        
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
                
            # Green for UP, ACCESSIBLE, or Whitelabel responses
            if any(keyword in status_text for keyword in ['UP', 'ACCESSIBLE', 'Whitelabel']):
                style_commands.append(('BACKGROUND', (1, i), (1, i), colors.HexColor('#E8F5E8')))
            elif any(keyword in status_text for keyword in ['DOWN', 'ERROR', 'TIMEOUT', 'UNREACHABLE']):
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

def analyze_pod_logs(v1, namespace, pod_name, container_name=None):
    """Intelligently analyze pod logs to find root cause of failures"""
    try:
        # Get more logs for better analysis (last 50 lines)
        if container_name:
            log_response = v1.read_namespaced_pod_log(
                name=pod_name,
                namespace=namespace,
                container=container_name,
                tail_lines=50
            )
        else:
            log_response = v1.read_namespaced_pod_log(
                name=pod_name,
                namespace=namespace,
                tail_lines=50
            )
        
        log_lines = log_response.strip().split('\n')
        
        # Pattern matching for common failure causes
        error_patterns = {
            'OutOfMemoryError': [
                r'java\.lang\.OutOfMemoryError',
                r'OutOfMemoryError',
                r'out of memory',
                r'Cannot allocate memory'
            ],
            'Port Already in Use': [
                r'Port \d+ is already in use',
                r'Address already in use',
                r'bind.*address already in use'
            ],
            'Database Connection Failed': [
                r'Connection refused.*\d+',
                r'Unable to connect to database',
                r'Database connection failed',
                r'Connection timeout',
                r'No route to host.*database'
            ],
            'Configuration Error': [
                r'Configuration.*error',
                r'Invalid configuration',
                r'Missing.*configuration',
                r'Unable to load config'
            ],
            'Permission Denied': [
                r'Permission denied',
                r'Access denied',
                r'Forbidden',
                r'insufficient.*permission'
            ],
            'File Not Found': [
                r'No such file or directory',
                r'FileNotFoundException',
                r'File not found'
            ],
            'Network Issue': [
                r'Connection refused',
                r'Network.*unreachable',
                r'Timeout.*connection',
                r'DNS.*resolution.*failed'
            ],
            'Application Startup Failed': [
                r'Application failed to start',
                r'Failed to start.*application',
                r'Startup.*failed',
                r'Unable to start.*server'
            ]
        }
        
        # Analyze logs for specific patterns
        for log_line in reversed(log_lines[-20:]):  # Check last 20 lines
            log_line_lower = log_line.lower()
            
            for error_type, patterns in error_patterns.items():
                for pattern in patterns:
                    if re.search(pattern, log_line, re.IGNORECASE):
                        # Extract relevant part of the error message
                        if len(log_line) > 100:
                            # Find the error part and extract context
                            error_start = max(0, log_line.lower().find(pattern.lower()) - 20)
                            error_end = min(len(log_line), error_start + 80)
                            extracted_error = log_line[error_start:error_end].strip()
                        else:
                            extracted_error = log_line.strip()
                        
                        return f"{error_type}: {extracted_error}"
        
        # If no specific pattern found, look for general error keywords
        for log_line in reversed(log_lines[-10:]):  # Check last 10 lines
            if any(keyword in log_line.lower() for keyword in ['error', 'exception', 'failed', 'fatal']):
                if len(log_line) > 100:
                    # Extract key part of the error
                    error_part = log_line[:100] + "..."
                else:
                    error_part = log_line.strip()
                return f"General Error: {error_part}"
        
        # If still no specific error found, return generic message
        return "Restart loop detected - no specific error pattern identified"
        
    except Exception as e:
        return f"Log analysis failed: {str(e)}"

def get_pod_exit_code(pod):
    """Get the exit code from a terminated container"""
    if pod.status.container_statuses:
        for container in pod.status.container_statuses:
            if (container.state and container.state.terminated and 
                container.state.terminated.exit_code is not None):
                return container.state.terminated.exit_code
    return None

def analyze_pod_fault(pod, v1, namespace):
    """Analyze a pod to determine fault reason with intelligent log analysis"""
    pod_name = pod.metadata.name
    reasons = []
    root_cause = None
    
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
    
    # Check container states for detailed issues
    if pod.status.container_statuses:
        for container in pod.status.container_statuses:
            container_name = container.name
            
            # Check for crash loop back off - get intelligent analysis
            if (container.state and container.state.waiting and 
                container.state.waiting.reason == 'CrashLoopBackOff'):
                reasons.append(f"Container {container_name}: CrashLoopBackOff")
                # Get intelligent log analysis for crashing container
                root_cause = analyze_pod_logs(v1, namespace, pod_name, container_name)
                
                # Also check exit code
                exit_code = get_pod_exit_code(pod)
                if exit_code:
                    root_cause += f" (Exit Code: {exit_code})"
            
            # Check for image pull errors
            elif (container.state and container.state.waiting and 
                  container.state.waiting.reason in ['ImagePullBackOff', 'ErrImagePull']):
                reasons.append(f"Container {container_name}: {container.state.waiting.reason}")
                if container.state.waiting.message:
                    root_cause = f"Image Error: {container.state.waiting.message}"
            
            # Check for config errors
            elif (container.state and container.state.waiting and 
                  container.state.waiting.reason == 'CreateContainerConfigError'):
                reasons.append(f"Container {container_name}: Config Error")
                if container.state.waiting.message:
                    root_cause = f"Config Error: {container.state.waiting.message}"
            
            # Check for high restart count with current issues
            elif container.restart_count > 3 and not container.ready:
                reasons.append(f"Container {container_name}: High restarts ({container.restart_count}), not ready")
                # Get intelligent log analysis for frequently restarting container
                root_cause = analyze_pod_logs(v1, namespace, pod_name, container_name)
    
    # Check pod conditions for additional insights
    if pod.status.conditions and not root_cause:
        for condition in pod.status.conditions:
            if condition.status == 'False' and condition.type in ['Ready', 'ContainersReady']:
                if condition.reason and condition.reason not in [r.split(':')[-1].strip() for r in reasons]:
                    reasons.append(f"{condition.type}: {condition.reason}")
                    if condition.message:
                        root_cause = f"Readiness Issue: {condition.message}"
    
    return reasons, root_cause

def get_pod_stats(pods, selector, v1, namespace):
    """Get enhanced pod statistics for a service with intelligent fault analysis"""
    matching_pods = [pod for pod in pods.items 
                    if all((pod.metadata.labels or {}).get(k) == v for k, v in selector.items())]
    
    total_pods = len(matching_pods)
    faulty_pod_details = []
    
    for pod in matching_pods:
        # Check for fault conditions
        is_faulty = False
        pod_name = pod.metadata.name
        
        # Basic fault checks
        if pod.status.phase in ['Failed', 'Pending']:
            is_faulty = True
        
        # Container state checks
        if pod.status.container_statuses:
            for container in pod.status.container_statuses:
                # Crash loop back off is always faulty
                if (container.state and container.state.waiting and 
                    container.state.waiting.reason == 'CrashLoopBackOff'):
                    is_faulty = True
                
                # High restart count with readiness issues
                elif container.restart_count > 3 and not container.ready:
                    is_faulty = True
                
                # Image or config errors
                elif (container.state and container.state.waiting and 
                      container.state.waiting.reason in ['ImagePullBackOff', 'ErrImagePull', 'CreateContainerConfigError']):
                    is_faulty = True
        
        if is_faulty:
            # Get intelligent fault analysis
            reasons, root_cause = analyze_pod_fault(pod, v1, namespace)
            
            faulty_pod_details.append({
                'name': pod_name,
                'reasons': reasons,
                'root_cause': root_cause,
                'detail': f"{pod_name}: {root_cause}" if root_cause else f"{pod_name}: {'; '.join(reasons[:1])}"
            })
    
    return total_pods, faulty_pod_details, matching_pods

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
        
        # Get enhanced pod statistics
        total_pods, faulty_pod_details, matching_pods = get_pod_stats(pods, selector, v1, namespace)
        
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
                'faulty_pod_details': faulty_pod_details
            }
        elif ingress_endpoint and not health_path:
            # Service has ingress but no health probe - test basic connectivity
            basic_endpoints[svc_name] = {
                'service': svc_name,
                'endpoint': ingress_endpoint,
                'total_pods': total_pods,
                'faulty_pod_details': faulty_pod_details
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

def format_root_cause_display(faulty_pod_details):
    """Format root cause analysis for console display"""
    if not faulty_pod_details:
        return f"{C.G}0: None{C.E}"
    
    fault_count = len(faulty_pod_details)
    
    # For console display, show pod names with root cause
    display_parts = []
    for pod_detail in faulty_pod_details:
        pod_name = pod_detail['name']
        root_cause = pod_detail.get('root_cause', 'Unknown issue')
        
        if root_cause:
            # Truncate long root causes for console
            if len(root_cause) > 60:
                short_cause = root_cause[:60] + "..."
            else:
                short_cause = root_cause
            display_parts.append(f"{pod_name} → {short_cause}")
        else:
            display_parts.append(pod_name)
    
    # Limit display for console readability
    if len(display_parts) > 2:
        shown = display_parts[:2]
        remaining = len(display_parts) - 2
        display_text = f"{C.R}{fault_count}: {'; '.join(shown)}... (+{remaining} more){C.E}"
    else:
        display_text = f"{C.R}{fault_count}: {'; '.join(display_parts)}{C.E}"
    
    return display_text

def format_root_cause_for_pdf(faulty_pod_details):
    """Format root cause analysis for PDF with detailed information"""
    if not faulty_pod_details:
        return "0: None"
    
    fault_count = len(faulty_pod_details)
    
    # For PDF, include detailed root cause analysis
    display_parts = []
    for pod_detail in faulty_pod_details:
        pod_name = pod_detail['name']
        root_cause = pod_detail.get('root_cause', 'Unknown issue')
        
        if root_cause:
            display_parts.append(f"{pod_name} → {root_cause}")
        else:
            reasons = pod_detail.get('reasons', [])
            if reasons:
                display_parts.append(f"{pod_name} → {'; '.join(reasons[:1])}")
            else:
                display_parts.append(pod_name)
    
    return f"{fault_count}: " + '; '.join(display_parts)

def check_health_endpoints(endpoints, namespace):
    """Check health endpoints with enhanced fault reporting and error codes"""
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
        faulty_pod_details = ep['faulty_pod_details']
        
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
                # Show specific HTTP error codes
                print(f"{C.R}❌ HTTP {response.status_code}{C.E}")
                health_status = f'🔴 HTTP {response.status_code}'
            
            # Enhanced root cause display
            root_cause_display_console = format_root_cause_display(faulty_pod_details)
            root_cause_display_pdf = format_root_cause_for_pdf(faulty_pod_details)
            
            results.append([service_name, health_status, str(total_pods), root_cause_display_pdf])
            
            # Show intelligent fault analysis if verbose mode or critical issues
            if faulty_pod_details:
                for pod_detail in faulty_pod_details[:1]:  # Show first faulty pod in detail
                    root_cause = pod_detail.get('root_cause')
                    if root_cause:
                        print(f"    └─ 🔍 {pod_detail['name']}: {root_cause}")
            
        except requests.exceptions.Timeout:
            print(f"{C.R}⏱️  TIMEOUT{C.E}")
            root_cause_display = format_root_cause_for_pdf(faulty_pod_details)
            results.append([service_name, '🔴 TIMEOUT', str(total_pods), root_cause_display])
        except requests.exceptions.ConnectionError:
            print(f"{C.R}🚫 UNREACHABLE{C.E}")
            root_cause_display = format_root_cause_for_pdf(faulty_pod_details)
            results.append([service_name, '🔴 UNREACHABLE', str(total_pods), root_cause_display])
        except Exception as e:
            print(f"{C.R}💥 ERROR: {str(e)}{C.E}")
            root_cause_display = format_root_cause_for_pdf(faulty_pod_details)
            results.append([service_name, f'🔴 ERROR: {str(e)}', str(total_pods), root_cause_display])
    
    return results, healthy_count

def check_basic_connectivity(basic_endpoints, namespace, debug=False):
    """Check basic connectivity for services without health endpoints with enhanced service up detection"""
    if not basic_endpoints:
        return []
    
    print(f"\n{C.B}{C.C}🌐 Basic Connectivity Check: {namespace} ({len(basic_endpoints)} services){C.E}")
    print(f"{C.C}{'─' * 70}{C.E}")
    
    results = []
    
    for i, ep in enumerate(basic_endpoints, 1):
        service_name = ep['service']
        endpoint_url = ep['endpoint']
        total_pods = ep['total_pods']
        faulty_pod_details = ep['faulty_pod_details']
        
        print(f"[{i}/{len(basic_endpoints)}] {service_name:<20}", end=' ')
        
        try:
            response = requests.get(endpoint_url, timeout=5, verify=False, allow_redirects=True)
            response_text = response.text.lower()
            
            # Debug output
            if debug:
                print(f"\n    🔍 DEBUG - Status: {response.status_code}")
                print(f"    🔍 DEBUG - Response preview: {response_text[:200]}...")
            
            # Primary check: Whitelabel Error Page means service is UP
            is_whitelabel_error = 'whitelabel error page' in response_text
            
            # Secondary checks for other service up indicators
            other_service_indicators = [
                'cannot get /',
                'this application has no explicit mapping',
                'there was an unexpected error',
                'no such label',
                'fallback'
            ]
            
            has_other_indicators = any(indicator in response_text for indicator in other_service_indicators)
            
            # Service is responding if we see whitelabel error page OR other indicators
            is_service_responding = is_whitelabel_error or has_other_indicators
            
            # Debug output for detection
            if debug:
                print(f"    🔍 DEBUG - Whitelabel detected: {is_whitelabel_error}")
                print(f"    🔍 DEBUG - Other indicators: {has_other_indicators}")
                print(f"    🔍 DEBUG - Service responding: {is_service_responding}")
            
            # Status determination logic
            if response.status_code == 200:
                print(f"{C.G}✅ ACCESSIBLE{C.E}")
                connectivity_status = '🟢 ACCESSIBLE'
            elif response.status_code in [301, 302, 403]:  # Standard accessible responses
                print(f"{C.G}✅ ACCESSIBLE{C.E}")
                connectivity_status = '🟢 ACCESSIBLE'
            elif is_whitelabel_error:
                # Explicitly handle Whitelabel Error Page as UP
                print(f"{C.G}✅ UP (Whitelabel Error Page){C.E}")
                connectivity_status = '🟢 UP (Whitelabel Error Page)'
            elif is_service_responding:
                # Other service indicators detected
                print(f"{C.G}✅ UP (Service Responding){C.E}")
                connectivity_status = '🟢 UP (Service Responding)'
            elif response.status_code == 404:
                # True 404 without any service indicators
                print(f"{C.Y}⚠️  HTTP 404{C.E}")
                connectivity_status = '🟡 HTTP 404'
            elif response.status_code == 503:
                print(f"{C.R}❌ HTTP 503{C.E}")
                connectivity_status = '🔴 HTTP 503'
            else:
                # Other HTTP error codes for non-responding services
                print(f"{C.R}❌ HTTP {response.status_code}{C.E}")
                connectivity_status = f'🔴 HTTP {response.status_code}'
            
            # Enhanced root cause display
            root_cause_display = format_root_cause_for_pdf(faulty_pod_details)
            results.append([service_name, connectivity_status, str(total_pods), root_cause_display])
            
            # Show intelligent fault analysis for critical issues
            if faulty_pod_details:
                for pod_detail in faulty_pod_details[:1]:  # Show first faulty pod in detail
                    root_cause = pod_detail.get('root_cause')
                    if root_cause:
                        print(f"    └─ 🔍 {pod_detail['name']}: {root_cause}")
            
        except requests.exceptions.Timeout:
            print(f"{C.R}⏱️  TIMEOUT{C.E}")
            root_cause_display = format_root_cause_for_pdf(faulty_pod_details)
            results.append([service_name, '🔴 TIMEOUT', str(total_pods), root_cause_display])
        except requests.exceptions.ConnectionError:
            print(f"{C.R}🚫 UNREACHABLE{C.E}")
            root_cause_display = format_root_cause_for_pdf(faulty_pod_details)
            results.append([service_name, '🔴 UNREACHABLE', str(total_pods), root_cause_display])
        except Exception as e:
            print(f"{C.R}💥 ERROR: {str(e)}{C.E}")
            root_cause_display = format_root_cause_for_pdf(faulty_pod_details)
            results.append([service_name, f'🔴 ERROR: {str(e)}', str(total_pods), root_cause_display])
    
    return results

def print_results(health_results, healthy_count, basic_results, services_no_selector, services_no_health_probe, services_no_ingress, suspended_services):
    # Calculate overall health excluding suspended services
    active_services = len(health_results) + len(basic_results)
    
    # Count accessible services (including those showing Whitelabel Error Page or other UP indicators)
    accessible_count = 0
    if basic_results:
        for result in basic_results:
            status = result[1]
            # Count as accessible if status contains ACCESSIBLE, UP, or Whitelabel
            if any(keyword in status for keyword in ['ACCESSIBLE', 'UP', 'Whitelabel']):
                accessible_count += 1
    
    total_healthy = healthy_count + accessible_count
    
    # Health check results
    if health_results:
        total_endpoints = len(health_results)
        success_rate = (healthy_count/total_endpoints)*100
        
        print(f"\n{C.B}📊 Health Check Results{C.E}")
        print(tabulate(health_results, headers=['Service', 'Status', 'Total Pods', 'Root Cause Analysis'], tablefmt='simple'))
        
        print(f"\n{C.B}Health Stats:{C.E} {C.G}{healthy_count}/{total_endpoints} healthy{C.E} ({success_rate:.0f}%)")
    
    # Basic connectivity results
    if basic_results:
        print(f"\n{C.B}🌐 Basic Connectivity Results{C.E}")
        print(tabulate(basic_results, headers=['Service', 'Status', 'Total Pods', 'Root Cause Analysis'], tablefmt='simple'))
        
        basic_success_rate = (accessible_count/len(basic_results))*100
        print(f"\n{C.B}Connectivity Stats:{C.E} {C.G}{accessible_count}/{len(basic_results)} responding{C.E} ({basic_success_rate:.0f}%)")
    
    # Overall system health (excluding suspended services)
    if active_services > 0:
        overall_health_rate = (total_healthy / active_services) * 100
        print(f"\n{C.B}Overall System Health:{C.E} {C.G}{total_healthy}/{active_services} operational{C.E} ({overall_health_rate:.1f}%)")
        print(f"{C.B}(Suspended services excluded from health calculation){C.E}")
    
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
    
    # Overall health status (based on active services only)
    if active_services > 0:
        if overall_health_rate >= 95:
            print(f"\n{C.G}🎉 System operating excellently{C.E}")
        elif overall_health_rate >= 85:
            print(f"\n{C.G}✅ System healthy{C.E}")
        elif overall_health_rate >= 70:
            print(f"\n{C.Y}⚠️  Some issues detected{C.E}")
        else:
            print(f"\n{C.R}🚨 Multiple services down{C.E}")
    else:
        print(f"\n{C.Y}⚠️  No active services to monitor{C.E}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="K8s health check monitor with intelligent fault analysis")
    parser.add_argument("namespace", help="Kubernetes namespace")
    parser.add_argument("--output-format", choices=['console', 'pdf', 'both'], 
                       default='console', help="Output format (default: console)")
    parser.add_argument("--output-dir", default="reports", 
                       help="Directory for reports (default: reports)")
    parser.add_argument("--verbose", "-v", action="store_true",
                       help="Show detailed fault analysis for all pods")
    parser.add_argument("--debug", "-d", action="store_true",
                       help="Show response content for debugging service detection")
    args = parser.parse_args()
    
    try:
        (health_endpoints, basic_endpoints, services_no_selector, 
         services_no_health_probe, services_no_ingress, suspended_services) = get_health_check_endpoints(args.namespace)
        
        # Check health endpoints
        health_results, healthy_count = check_health_endpoints(health_endpoints, args.namespace)
        
        # Check basic connectivity for services without health probes
        basic_results = check_basic_connectivity(basic_endpoints, args.namespace, args.debug)
        
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
