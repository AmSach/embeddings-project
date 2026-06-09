let networkGraph = null;

// Node group color definitions to match CSS styling
const GROUP_COLORS = {
    "Country": {
        background: '#6366f1',
        border: '#4f46e5',
        highlight: { background: '#818cf8', border: '#6366f1' }
    },
    "Region": {
        background: '#10b981',
        border: '#059669',
        highlight: { background: '#34d399', border: '#10b981' }
    },
    "Military Group": {
        background: '#f59e0b',
        border: '#d97706',
        highlight: { background: '#fbbf24', border: '#f59e0b' }
    },
    "Dispute": {
        background: '#ec4899',
        border: '#db2777',
        highlight: { background: '#f472b6', border: '#ec4899' }
    },
    "Treaty": {
        background: '#06b6d4',
        border: '#0891b2',
        highlight: { background: '#22d3ee', border: '#06b6d4' }
    },
    "Company": {
        background: '#8b5cf6',
        border: '#7c3aed',
        highlight: { background: '#a78bfa', border: '#8b5cf6' }
    },
    "Unknown": {
        background: '#94a3b8',
        border: '#475569',
        highlight: { background: '#cbd5e1', border: '#94a3b8' }
    }
};

async function loadGraphData() {
    const graphContainer = document.getElementById('knowledge-graph');
    graphContainer.innerHTML = '<div class="empty-state"><i class="fa-solid fa-spinner fa-spin"></i><p>Compiling database relationships...</p></div>';
    
    try {
        const res = await fetch('/api/graph');
        const data = await res.json();
        
        if (data.nodes.length === 0) {
            graphContainer.innerHTML = '<div class="empty-state"><i class="fa-solid fa-circle-nodes"></i><p>No entity relationships found in database. Run the auto crawler to discover geopolitical connections.</p></div>';
            return;
        }

        // 1. Format Nodes
        const nodes = data.nodes.map(n => {
            const groupColor = GROUP_COLORS[n.type] || GROUP_COLORS["Unknown"];
            
            return {
                id: n.id,
                label: n.label,
                title: `Type: ${n.type}\nRelevance weight: ${n.weight}`,
                group: n.type,
                value: Math.max(10, n.weight * 3), // Sizing by weight
                color: groupColor,
                font: {
                    color: '#f3f4f6',
                    face: 'Outfit',
                    size: 14
                }
            };
        });

        // 2. Format Edges
        const edges = data.links.map((l, index) => {
            return {
                id: `edge-${index}`,
                from: l.source,
                to: l.target,
                title: `Connection: ${l.description}\nSource: ${l.source_title}`,
                color: {
                    color: 'rgba(99, 102, 241, 0.25)',
                    highlight: '#6366f1',
                    hover: '#6366f1'
                },
                width: 2,
                // Attach reference info to the edge object to retrieve on click
                referenceInfo: {
                    description: l.description,
                    source_title: l.source_title,
                    source_url: l.source_url,
                    trust_score: l.trust_score
                }
            };
        });

        // 3. Clear container
        graphContainer.innerHTML = '';

        // 4. Initialize Vis.js Network
        const graphData = {
            nodes: new vis.DataSet(nodes),
            edges: new vis.DataSet(edges)
        };

        const options = {
            nodes: {
                shape: 'dot',
                scaling: {
                    min: 12,
                    max: 30
                },
                shadow: {
                    enabled: true,
                    color: 'rgba(0,0,0,0.5)',
                    size: 8,
                    x: 2,
                    y: 2
                }
            },
            edges: {
                smooth: {
                    type: 'continuous',
                    roundness: 0.5
                },
                hoverWidth: 1.5
            },
            physics: {
                barnesHut: {
                    gravitationalConstant: -12000,
                    centralGravity: 0.3,
                    springLength: 120,
                    springConstant: 0.04,
                    damping: 0.09,
                    avoidOverlap: 0.5
                },
                stabilization: {
                    enabled: true,
                    iterations: 150,
                    updateInterval: 25
                }
            },
            interaction: {
                hover: true,
                tooltipDelay: 300,
                zoomView: true,
                dragView: true
            }
        };

        networkGraph = new vis.Network(graphContainer, graphData, options);

        // 5. Connect click event to open connection details
        networkGraph.on("click", function(params) {
            if (params.edges.length > 0 && params.nodes.length === 0) {
                const clickedEdgeId = params.edges[0];
                const edgeObj = graphData.edges.get(clickedEdgeId);
                
                if (edgeObj && edgeObj.referenceInfo) {
                    showRelationDetailsModal(edgeObj.from, edgeObj.to, edgeObj.referenceInfo);
                }
            }
        });

    } catch (err) {
        console.error("Error drawing vis network:", err);
        graphContainer.innerHTML = `<div class="empty-state-small error">Error building network visualization: ${err}</div>`;
    }
}

function showRelationDetailsModal(node1, node2, refInfo) {
    // We re-use the Source Detail Modal to show relation co-occurrences beautifully!
    document.getElementById('source-modal-title').innerText = `Relational Nexus: ${node1} ↔ ${node2}`;
    document.getElementById('source-modal-link').href = refInfo.source_url;
    document.getElementById('source-modal-category').innerText = "Entity Connection";
    
    let trustClass = 'trust-low';
    let trustLabel = 'Opinion';
    if (refInfo.trust_score >= 0.9) {
        trustClass = 'trust-high';
        trustLabel = 'UN/Gov Document';
    } else if (refInfo.trust_score >= 0.7) {
        trustClass = 'trust-medium';
        trustLabel = 'Credible Media';
    }
    
    const badge = document.getElementById('source-modal-trust');
    badge.className = `trust-badge ${trustClass}`;
    badge.innerText = `Source Trust Score: ${refInfo.trust_score.toFixed(2)} (${trustLabel})`;

    const contentArea = document.getElementById('source-modal-content');
    contentArea.innerHTML = `
        <div style="margin-top: 15px;">
            <h4 style="font-family: var(--font-header); color: var(--accent-color);">Context of co-occurrence:</h4>
            <div class="source-modal-chunk" style="font-size: 1.1rem; font-style: italic;">
                "${refInfo.description}"
            </div>
        </div>
        <div style="margin-top: 25px;">
            <h4 style="font-family: var(--font-header);">Origin Document:</h4>
            <p style="font-size: 0.95rem; font-weight: 500; color: var(--text-primary);">${refInfo.source_title}</p>
        </div>
    `;

    document.getElementById('modal-source-view').classList.remove('hidden');
}
