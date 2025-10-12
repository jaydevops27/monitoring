# Complete Prompt to Recreate Kubernetes Health Monitoring Dashboard

## Project Overview
Create a **Kubernetes Health Monitoring Dashboard** using Flask (Python) and vanilla JavaScript with Chart.js. The application monitors Kubernetes clusters with an **Organizational Unit (OU) based architecture** and displays **service-centric health metrics**.

---

## Technical Stack
- **Backend**: Python 3.12, Flask 3.0.0, Kubernetes Python Client 28.1.0
- **Frontend**: HTML5, CSS3, Vanilla JavaScript, Chart.js 4.4.0
- **Architecture**: Three-tier navigation (Dashboard → OU → Namespace)
- **Port**: 8080
- **Auto-refresh**: Every 30 seconds

---

## Core Requirements

### 1. Backend Structure (Flask Application)

#### File: `app.py`
- Flask web server running on port 8080 with debug mode enabled
- Define 3 Organizational Units (OUs):
  - **B01 - System & Infrastructure**: Contains namespaces [`kube-node-lease`, `kube-public`, `kube-system`, `kubernetes-dashboard`]
  - **B02 - Production**: Contains namespaces [`default`, `ingress-nginx`]
  - **B03 - Testing & Development**: Contains namespaces [`clean-test`, `test-issues`]
- Each OU has id, name, description, color (blue/magenta/orange), and namespaces list

#### Routes Required:
1. `GET /` - Main dashboard showing all OUs
2. `GET /ou/<ou_id>` - OU detail page showing namespaces in that OU
3. `GET /namespace/<namespace_name>` - Namespace detail showing services and pods
4. `GET /api/health/overview` - JSON API returning all OUs with health metrics
5. `GET /api/health/ou/<ou_id>` - JSON API for specific OU health
6. `GET /api/health/namespace/<name>` - JSON API for namespace detailed health

#### File: `k8s_client.py`
Kubernetes API client wrapper with these methods:

**`get_all_namespaces_health()`**
- Returns list of all namespaces with health metrics
- Each namespace includes: namespace name, total_pods, healthy_pods, unhealthy_pods, health_percentage, services count, healthy_services, unhealthy_services

**`get_namespace_health(namespace)`**
- Fetch pods using `core_api.list_namespaced_pod()`
- Fetch services using `core_api.list_namespaced_service()`
- Calculate service-level health by:
  - Match pods to services using service selectors
  - Count service as healthy if >50% of its pods are healthy
  - Exclude 'kubernetes' service from counts
- Return: namespace, total_pods, healthy_pods, unhealthy_pods, health_percentage, services, healthy_services, unhealthy_services

**`get_namespace_detailed_health(namespace)`**
- Fetch pods, services, deployments, ingresses
- Group pods by service using service selectors
- Create service_groups dictionary with pods organized by service
- Orphaned pods (no service) go in '_orphaned' group
- Calculate service health: healthy if >50% pods healthy
- Return detailed object with service_groups array

**`_is_pod_healthy(pod)`**
- Check pod.status.phase == 'Running'
- Verify all containers have ready=True

---

### 2. Frontend Structure

#### Three HTML Templates:

**`templates/index.html` - Main Dashboard**
- Header with "Kubernetes Health Monitoring Dashboard"
- Top stats showing: Overall Health %, Total Pods, Healthy Pods, Unhealthy Pods
- Refresh button
- Section titled "Organizational Units (OUs)" with description "Click on an OU to view its namespaces and detailed health metrics"
- OU cards grid showing 3 OUs
- Each OU card displays:
  - OU ID badge (B01/B02/B03)
  - OU name and description
  - Health percentage circle (color-coded: green ≥80%, yellow ≥50%, red <50%)
  - Stats: Total Pods, Healthy, Unhealthy
  - Namespace tags showing all namespaces in that OU
  - Left border color matching OU color
  - Clickable - navigates to `/ou/{ou_id}`
  - Hover effect: lifts up slightly (NO arrow animation)
- Auto-refresh every 30 seconds
- Last updated timestamp at bottom

**`templates/ou_detail.html` - OU Detail Page**
- Breadcrumb navigation: Dashboard / {OU_ID}
- Page title: "OU: {OU_NAME}"
- Two charts at top:
  - **Namespace Health Comparison** (Bar Chart): Shows service health % for each namespace
  - **OU Health Distribution** (Doughnut Chart): Healthy vs Unhealthy pods
- Section "Namespaces in this OU"
- Namespace cards grid showing all namespaces in the OU
- Each namespace card displays:
  - Namespace name as heading
  - Service health percentage badge (color-coded)
  - Total Services count
  - Healthy Services count
  - Unhealthy Services count
  - Total Pods count (for reference)
  - Clickable - navigates to `/namespace/{namespace_name}`
- Auto-refresh every 30 seconds

**`templates/namespace_detail.html` - Namespace Detail Page**
- Breadcrumb navigation: Dashboard / {OU_ID} / {namespace_name}
- Page title: "Namespace: {namespace_name}"
- Top stats showing:
  - Service Health % (calculated from healthy_services / total_services)
  - Total Services
  - Healthy Services
  - Unhealthy Services
- Refresh button
- Chart: **Service Health Status** (Doughnut Chart showing healthy vs unhealthy services)
- Section "Services & Their Pods"
- Search bar to filter services
- Pagination controls (10 services per page)
- Collapsible service cards showing:
  - Service name (expandable header)
  - Service hostname and type
  - Pod count (total/healthy/unhealthy)
  - Pod list with status indicators
  - Each pod shows: name, status badge (Running/Failed/Pending), restart count
  - "View Logs" button for each pod
- Modal for viewing pod logs with container selector
- Auto-refresh every 30 seconds

---

### 3. JavaScript Files

**`static/js/dashboard.js`**
- Fetch data from `/api/health/overview`
- Update top stats (overall health, total pods, healthy/unhealthy)
- Render OU cards with click handlers to navigate to OU detail page
- Auto-refresh every 30 seconds
- Color constants: SUCCESS_COLOR = '#28a745', DANGER_COLOR = '#dc3545'

**`static/js/ou_detail.js`**
- Extract OU ID from URL pathname
- Fetch data from `/api/health/ou/{ou_id}`
- Render two charts using Chart.js:
  - Namespace comparison bar chart (horizontal bars showing service health %)
  - Health pie chart (doughnut showing healthy vs unhealthy pods)
- Render namespace cards with service metrics
- Calculate service health percentage: (healthy_services / total_services) * 100
- Auto-refresh every 30 seconds

**`static/js/namespace_detail.js`**
- Extract namespace name from URL pathname
- Fetch data from `/api/health/namespace/{namespace_name}`
- Update header stats with SERVICE metrics (not pod metrics)
- Calculate service health percentage from healthy_services/total_services
- Render service health doughnut chart
- Implement search functionality for services
- Implement pagination (10 items per page)
- Collapsible service cards with expand/collapse animation
- Pod log viewer modal with container selection
- Auto-refresh every 30 seconds

---

### 4. CSS Styling (`static/css/style.css`)

#### Design Requirements:
- **Color Scheme**:
  - Primary: #e91e63 (magenta/pink)
  - Success: #28a745 (green)
  - Warning: #ffc107 (yellow/orange)
  - Danger: #dc3545 (red)
  - Background: #f5f7fa
  - Card background: #ffffff
  
- **Typography**:
  - Font: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif
  - Headings: Bold, primary color
  
- **Components**:
  - **Breadcrumb**: Pink links with separators, current page in bold
  - **Stat Cards**: White cards with shadow, large numbers, labels below
  - **OU Cards**: 
    - White background, rounded corners
    - Left border (5px) in OU color
    - Shadow effect
    - Hover: lifts up with translateY(-5px)
    - NO arrow indicator or ::before pseudo-element
  - **Namespace Cards**:
    - Pink top border
    - Health badge in top right (color-coded)
    - Stats in row format
    - Clickable with hover effect
  - **Charts**: 
    - White container with shadow
    - Hover effect (lifts up slightly)
    - Responsive canvas
  - **Service Cards**:
    - Collapsible with smooth animation
    - Pink header when collapsed
    - Pod list visible when expanded
    - Status badges (green/red/yellow)
  - **Buttons**:
    - Primary: Pink background, white text
    - Hover: Darker pink
    - Refresh button with icon
  - **Modal**:
    - Dark overlay
    - White content box centered
    - Close button
    - Log viewer with monospace font, dark background

- **Responsive Design**:
  - Grid layouts for OU and namespace cards
  - Mobile-friendly with media queries
  - Flexible chart containers

---

### 5. Service-Centric Health Calculation Logic

**CRITICAL**: The application is SERVICE-CENTRIC, not pod-centric.

#### Health Calculation Rules:
1. **Service Health**: A service is healthy if **MORE than 50%** of its pods are healthy
2. **Namespace Service Health %**: (healthy_services / total_services) * 100
3. **Pod Health**: Pod is healthy if status.phase == 'Running' AND all containers ready == True
4. **Service Grouping**: 
   - Match pods to services using service.spec.selector labels
   - Pods without matching service go to "Standalone Pods" group
   - Exclude 'kubernetes' service from counts

#### Display Priority:
- **Dashboard (Main)**: Shows OU-level pod counts (aggregated)
- **OU Detail**: Shows service counts per namespace (Total Services, Healthy Services, Unhealthy Services)
- **Namespace Detail**: Shows service health % and service count at top, detailed service cards below

---

### 6. Additional Files

**`requirements.txt`**
```
Flask==3.0.0
kubernetes==28.1.0
```

**`start.sh`** (executable)
```bash
#!/bin/bash
source venv/bin/activate
python app.py
```

**`test_connection.py`**
- Test Kubernetes API connectivity
- Load kubeconfig
- List all namespaces
- Print connection success/failure

---

### 7. Navigation Flow

```
Dashboard (/)
  └─> Click OU Card → OU Detail (/ou/B01)
       └─> Click Namespace Card → Namespace Detail (/namespace/kube-system)
            └─> Click Breadcrumb → Back to OU or Dashboard
```

**Breadcrumb Requirements**:
- Format: `Dashboard / B01 / namespace-name`
- Each segment is clickable (except current page)
- Current page shown in bold with class "current"
- Pink colored links with hover effect

---

### 8. Chart Specifications

**Chart.js 4.4.0 Configuration**:

1. **Namespace Comparison Bar Chart** (OU page):
   - Type: horizontal bar
   - X-axis: 0-100% scale
   - Y-axis: Namespace names
   - Color: Green bars
   - Shows service health percentage per namespace

2. **Health Distribution Doughnut** (OU page):
   - Type: doughnut
   - Data: [healthy_pods, unhealthy_pods]
   - Colors: [green, red]
   - Legend at bottom
   - Tooltip shows count and percentage

3. **Service Health Doughnut** (Namespace page):
   - Type: doughnut
   - Data: [healthy_services, unhealthy_services]
   - Colors: [green, red]
   - Legend at bottom
   - Tooltip shows count and percentage

**NO LINE CHARTS** on main dashboard (removed for clean design)

---

### 9. API Response Formats

**`/api/health/overview`**:
```json
{
  "timestamp": "2025-10-12T11:44:14",
  "overall_health": 51.5,
  "total_pods": 33,
  "healthy_pods": 17,
  "unhealthy_pods": 16,
  "organizational_units": [
    {
      "id": "B01",
      "name": "System & Infrastructure",
      "description": "Core Kubernetes system components",
      "color": "#2196F3",
      "health_percentage": 90.0,
      "total_pods": 10,
      "healthy_pods": 9,
      "unhealthy_pods": 1,
      "namespaces": [...]
    }
  ]
}
```

**`/api/health/namespace/{name}`**:
```json
{
  "namespace": "default",
  "health_percentage": 50.0,
  "total_pods": 6,
  "healthy_pods": 3,
  "unhealthy_pods": 3,
  "services": 5,
  "healthy_services": 0,
  "unhealthy_services": 5,
  "service_groups": [
    {
      "name": "service-name",
      "hostname": "service-name.default.svc.cluster.local",
      "type": "ClusterIP",
      "pods": [...],
      "total_pods": 3,
      "healthy_pods": 1,
      "unhealthy_pods": 2
    }
  ]
}
```

---

### 10. Key Features

✅ **OU-based organization** - 3 predefined OUs with namespace grouping
✅ **Service-centric metrics** - Focus on service health, not individual pods
✅ **Three-tier navigation** - Dashboard → OU → Namespace with breadcrumbs
✅ **Interactive charts** - Chart.js visualizations at OU and namespace levels
✅ **Real-time monitoring** - Auto-refresh every 30 seconds
✅ **Search & pagination** - Filter services, 10 per page
✅ **Pod log viewer** - Modal with container selection
✅ **Collapsible service cards** - Expand/collapse animation
✅ **Responsive design** - Works on desktop and mobile
✅ **Color-coded health** - Green (≥80%), Yellow (≥50%), Red (<50%)
✅ **Clean UI** - No unnecessary arrows, minimal design

---

### 11. Setup Instructions

1. Create Python virtual environment: `python -m venv venv`
2. Activate: `source venv/bin/activate`
3. Install dependencies: `pip install -r requirements.txt`
4. Ensure kubeconfig is accessible at `~/.kube/config`
5. Test connection: `python test_connection.py`
6. Run application: `python app.py` or `./start.sh`
7. Open browser: `http://localhost:8080`

---

### 12. Critical Implementation Details

#### Service Health Calculation (MUST IMPLEMENT EXACTLY):
```python
# In get_namespace_health() and get_namespace_detailed_health()
service_health = {}
for service in service_list:
    service_selector = service.spec.selector or {}
    matching_pods = [pod for pod in pods if all(
        pod.metadata.labels.get(k) == v 
        for k, v in service_selector.items()
    )]
    
    if matching_pods:
        service_total = len(matching_pods)
        service_healthy = sum(1 for p in matching_pods if _is_pod_healthy(p))
        health_percentage = service_healthy / service_total
        
        # Service is healthy if MORE than 50% pods are healthy
        if health_percentage > 0.5:
            healthy_services += 1
```

#### Frontend Service Health Display:
```javascript
// Calculate service health percentage
const serviceHealthPercentage = totalServices > 0 
    ? ((healthyServices / totalServices) * 100).toFixed(1)
    : 0;

// Update DOM elements
document.getElementById('namespaceHealth').textContent = serviceHealthPercentage + '%';
document.getElementById('totalServices').textContent = totalServices;
document.getElementById('healthyServices').textContent = healthyServices;
document.getElementById('unhealthyServices').textContent = unhealthyServices;
```

#### CSS - NO Arrow on OU Cards:
```css
.ou-card {
    /* ... other styles ... */
    cursor: pointer;
    position: relative;
}

/* NO ::before pseudo-element with arrow */

.ou-card:hover {
    transform: translateY(-5px);
    box-shadow: 0 8px 25px rgba(0, 0, 0, 0.15);
}
```

---

## Final Checklist

- [ ] Flask app runs on port 8080
- [ ] 3 OUs defined with correct namespaces
- [ ] Service health calculated with >50% threshold
- [ ] Main dashboard shows OU cards (no charts)
- [ ] OU page shows 2 charts + namespace cards with service metrics
- [ ] Namespace page shows service health stats + service health chart
- [ ] Breadcrumb navigation works correctly
- [ ] Auto-refresh every 30 seconds on all pages
- [ ] Search and pagination on namespace detail page
- [ ] Pod log modal with container selection
- [ ] No arrow animation on OU cards
- [ ] Color scheme: Pink primary, green/yellow/red health indicators
- [ ] Responsive design with hover effects

---

## Expected Result

A fully functional Kubernetes health monitoring dashboard that:
- Organizes cluster resources by Organizational Units
- Displays service-level health metrics (not just pods)
- Provides intuitive three-tier navigation
- Auto-refreshes data every 30 seconds
- Shows interactive charts for health visualization
- Allows drilling down from OU → Namespace → Service → Pod
- Has clean, modern UI with pink/magenta theme
- Works with any Kubernetes cluster via kubeconfig

This recreates the application with 100% similarity to the original implementation.
