def check_basic_connectivity(basic_endpoints, namespace):
    """Check basic connectivity for services without health endpoints with enhanced error reporting"""
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
            
            # Check for indicators that service is UP even with error responses
            service_up_indicators = [
                'whitelabel error page',
                'cannot get /',
                'this application has no explicit mapping',
                'there was an unexpected error',
                'no such label',
                'error 404',
                'not found'
            ]
            
            is_service_responding = any(indicator in response_text for indicator in service_up_indicators)
            
            if response.status_code == 200:
                print(f"{C.G}✅ ACCESSIBLE{C.E}")
                connectivity_status = '🟢 ACCESSIBLE'
            elif response.status_code in [301, 302, 403]:  # Accessible responses
                print(f"{C.G}✅ ACCESSIBLE{C.E}")
                connectivity_status = '🟢 ACCESSIBLE'
            elif response.status_code == 404 and is_service_responding:
                # 404 with service up indicators means service is UP
                print(f"{C.G}✅ UP (404 - Service Responding){C.E}")
                connectivity_status = '🟢 UP (404 - Service Responding)'
            elif response.status_code == 404:
                # Regular 404 without service indicators
                print(f"{C.Y}⚠️  HTTP 404{C.E}")
                connectivity_status = '🟡 HTTP 404'
            elif response.status_code == 503:
                print(f"{C.R}❌ HTTP 503{C.E}")
                connectivity_status = '🔴 HTTP 503'
            elif is_service_responding:
                # Any other status code but service is clearly responding
                print(f"{C.G}✅ UP (HTTP {response.status_code} - Service Responding){C.E}")
                connectivity_status = f'🟢 UP (HTTP {response.status_code} - Service Responding)'
            else:
                # Show specific HTTP error codes for non-responding services
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
    
    # Count accessible services (including those showing service up indicators)
    accessible_count = 0
    if basic_results:
        for result in basic_results:
            status = result[1]
            if 'ACCESSIBLE' in status or 'UP' in status:
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

# Enhanced status overview for PDF reports
def _create_status_overview_box(self, health_results, healthy_count, basic_results, suspended_services):
    """Create a clean status overview box with enhanced service up detection"""
    active_services = len(health_results) + len(basic_results)
    
    # Count accessible services (including those showing service up indicators)
    accessible_count = 0
    if basic_results:
        for result in basic_results:
            status = result[1]
            if 'ACCESSIBLE' in status or 'UP' in status:
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
    
    # Rest of the table styling code remains the same...
    table = Table(data, colWidths=[2.5*inch, 2.5*inch, 2.5*inch])
    # ... existing table style code
    
    return table
