// graph.js - D3.js force-directed graph for node visualization

class BullyGraph {
    constructor(svgSelector) {
        this.svg = d3.select(svgSelector);
        this.width = 0;
        this.height = 0;
        this.nodes = [];
        this.nodeElements = null;
        this.simulation = null;
        this.messageLayer = null;
        this.nodeLayer = null;
        this.mainGroup = null;
        this.zoom = null;
        this.tooltip = null;
        this.currentDebugMessages = new Map();

        this.setupSVG();
        this.setupArrowMarkers();
        this.setupZoom();
        this.setupTooltip();

        // Handle resize
        window.addEventListener('resize', () => this.handleResize());
    }

    setupSVG() {
        const container = this.svg.node().parentElement;
        this.width = container.clientWidth;
        this.height = container.clientHeight;

        this.svg
            .attr('width', this.width)
            .attr('height', this.height);

        // Create main group that will be transformed for zoom/pan
        this.mainGroup = this.svg.append('g').attr('class', 'main-group');

        // Create layers inside main group
        this.messageLayer = this.mainGroup.append('g').attr('class', 'message-layer');
        this.nodeLayer = this.mainGroup.append('g').attr('class', 'node-layer');
    }

    setupZoom() {
        this.zoom = d3.zoom()
            .scaleExtent([0.1, 4])
            .on('zoom', (event) => {
                this.mainGroup.attr('transform', event.transform);
            });

        this.svg.call(this.zoom);
    }

    setupTooltip() {
        this.tooltip = d3.select('body').append('div')
            .attr('class', 'node-tooltip')
            .style('opacity', 0)
            .style('position', 'absolute')
            .style('pointer-events', 'none');
    }

    showTooltip(event, node) {
        const messages = this.currentDebugMessages.get(node.uid) || [];
        if (messages.length === 0) {
            this.hideTooltip();
            return;
        }

        this.tooltip
            .html(messages.join('<br>'))
            .style('left', (event.pageX + 15) + 'px')
            .style('top', (event.pageY - 10) + 'px')
            .transition()
            .duration(200)
            .style('opacity', 1);
    }

    hideTooltip() {
        this.tooltip
            .transition()
            .duration(200)
            .style('opacity', 0);
    }

    setDebugMessages(debugMap) {
        this.currentDebugMessages = debugMap;
    }

    setupArrowMarkers() {
        const defs = this.svg.append('defs');

        const markerTypes = ['heartbeat', 'election', 'ok', 'coordinator', 'ping', 'ack'];

        markerTypes.forEach(type => {
            defs.append('marker')
                .attr('id', `arrow-${type}`)
                .attr('viewBox', '0 -5 10 10')
                .attr('refX', 25)
                .attr('refY', 0)
                .attr('markerWidth', 6)
                .attr('markerHeight', 6)
                .attr('orient', 'auto')
                .append('path')
                .attr('d', 'M0,-5L10,0L0,5')
                .attr('class', type);
        });
    }

    handleResize() {
        const container = this.svg.node().parentElement;
        this.width = container.clientWidth;
        this.height = container.clientHeight;

        this.svg
            .attr('width', this.width)
            .attr('height', this.height);

        // Refit view on resize
        if (this.nodes.length > 0) {
            this.fitToView();
        }
    }

    fitToView(animate = true) {
        if (!this.nodes.length) return;

        const padding = 50; // Padding around nodes
        const nodeRadius = 25;

        // Calculate bounding box of all nodes
        let minX = Infinity, maxX = -Infinity;
        let minY = Infinity, maxY = -Infinity;

        this.nodes.forEach(node => {
            minX = Math.min(minX, node.x - nodeRadius);
            maxX = Math.max(maxX, node.x + nodeRadius);
            minY = Math.min(minY, node.y - nodeRadius);
            maxY = Math.max(maxY, node.y + nodeRadius);
        });

        // Add padding
        minX -= padding;
        maxX += padding;
        minY -= padding;
        maxY += padding;

        // Calculate required scale and translation
        const boxWidth = maxX - minX;
        const boxHeight = maxY - minY;

        const scale = Math.min(
            this.width / boxWidth,
            this.height / boxHeight,
            1.5 // Don't zoom in too much
        );

        const centerX = (minX + maxX) / 2;
        const centerY = (minY + maxY) / 2;

        const translateX = this.width / 2 - centerX * scale;
        const translateY = this.height / 2 - centerY * scale;

        const transform = d3.zoomIdentity
            .translate(translateX, translateY)
            .scale(scale);

        if (animate) {
            this.svg.transition()
                .duration(500)
                .call(this.zoom.transform, transform);
        } else {
            this.svg.call(this.zoom.transform, transform);
        }
    }

    initNodes(nodeUIDs) {
        // Create node data with circular initial positions
        const numNodes = nodeUIDs.length;
        const radius = Math.min(this.width, this.height) * 0.35;
        const centerX = this.width / 2;
        const centerY = this.height / 2;

        this.nodes = nodeUIDs.map((uid, i) => {
            const angle = (2 * Math.PI * i) / numNodes - Math.PI / 2;
            return {
                uid: uid,
                x: centerX + radius * Math.cos(angle),
                y: centerY + radius * Math.sin(angle),
                online: true,
                isLeader: false,
                inElection: false
            };
        });

        // Create force simulation
        this.simulation = d3.forceSimulation(this.nodes)
            .force('charge', d3.forceManyBody().strength(-300))
            .force('center', d3.forceCenter(this.width / 2, this.height / 2))
            .force('collision', d3.forceCollide().radius(40))
            .on('tick', () => this.tick());

        // Create node elements
        this.nodeElements = this.nodeLayer.selectAll('.node')
            .data(this.nodes, d => d.uid)
            .join('g')
            .attr('class', 'node online')
            .call(d3.drag()
                .on('start', (event, d) => this.dragStarted(event, d))
                .on('drag', (event, d) => this.dragged(event, d))
                .on('end', (event, d) => this.dragEnded(event, d)))
            .on('mouseenter', (event, d) => this.showTooltip(event, d))
            .on('mousemove', (event, d) => this.showTooltip(event, d))
            .on('mouseleave', () => this.hideTooltip());

        this.nodeElements.append('circle')
            .attr('r', 25);

        this.nodeElements.append('text')
            .text(d => d.uid);

        // Stop simulation after initial layout and fit to view
        setTimeout(() => {
            this.simulation.stop();
            this.fitToView(false);
        }, 2000);

        // Also fit to view immediately (without animation) for initial display
        setTimeout(() => {
            this.fitToView(false);
        }, 100);
    }

    tick() {
        if (this.nodeElements) {
            this.nodeElements.attr('transform', d => `translate(${d.x}, ${d.y})`);
        }
    }

    dragStarted(event, d) {
        if (!event.active) this.simulation.alphaTarget(0.3).restart();
        d.fx = d.x;
        d.fy = d.y;
    }

    dragged(event, d) {
        d.fx = event.x;
        d.fy = event.y;
    }

    dragEnded(event, d) {
        if (!event.active) this.simulation.alphaTarget(0);
        d.fx = null;
        d.fy = null;
    }

    updateState(nodeStates) {
        if (!this.nodes.length) return;

        // Create a map for quick lookup
        const stateMap = new Map();
        nodeStates.forEach(s => stateMap.set(s.uid, s));

        // Find the current leader (node that believes itself to be leader)
        let leaderUid = null;
        nodeStates.forEach(s => {
            if (s.online && s.leader === s.uid) {
                leaderUid = s.uid;
            }
        });

        // If no self-proclaimed leader, find consensus leader
        if (leaderUid === null) {
            const leaderCounts = new Map();
            nodeStates.forEach(s => {
                if (s.online && s.leader > 0) {
                    leaderCounts.set(s.leader, (leaderCounts.get(s.leader) || 0) + 1);
                }
            });
            let maxCount = 0;
            leaderCounts.forEach((count, uid) => {
                if (count > maxCount) {
                    maxCount = count;
                    leaderUid = uid;
                }
            });
        }

        // Update node data
        this.nodes.forEach(node => {
            const state = stateMap.get(node.uid);
            if (state) {
                node.online = state.online;
                node.isLeader = node.uid === leaderUid;
                node.inElection = state.election;
                node.believedLeader = state.leader;
            }
        });

        // Update visual classes
        this.nodeElements
            .attr('class', d => {
                let classes = ['node'];
                if (!d.online) {
                    classes.push('offline');
                } else {
                    classes.push('online');
                    if (d.isLeader) classes.push('leader');
                    if (d.inElection) classes.push('election');
                }
                return classes.join(' ');
            });

        return leaderUid;
    }

    showMessages(messages) {
        // Clear previous messages
        this.messageLayer.selectAll('.message-arrow').remove();
        this.messageLayer.selectAll('.message-label').remove();

        // Filter to only show sent messages (not receives)
        const sentMessages = messages.filter(m => m.direction === 'send');

        // Longer animation timing for educational clarity
        const staggerDelay = 150;
        const persistDuration = 2000; // Messages stay visible for 2 seconds

        // Create message arrows with labels
        sentMessages.forEach((msg, i) => {
            const srcNode = this.nodes.find(n => n.uid === msg.src);
            let dstNodes = [];

            if (msg.dst === -1) {
                // Broadcast - show to all other nodes
                dstNodes = this.nodes.filter(n => n.uid !== msg.src);
            } else {
                const dst = this.nodes.find(n => n.uid === msg.dst);
                if (dst) dstNodes = [dst];
            }

            if (!srcNode) return;

            dstNodes.forEach((dstNode, j) => {
                const delay = (i * staggerDelay) + (j * 50);

                // Create arrow line
                const line = this.messageLayer.append('line')
                    .attr('class', `message-arrow ${msg.type.toLowerCase()} ${msg.dropped ? 'dropped' : ''}`)
                    .attr('x1', srcNode.x)
                    .attr('y1', srcNode.y)
                    .attr('x2', dstNode.x)
                    .attr('y2', dstNode.y)
                    .attr('marker-end', `url(#arrow-${msg.type.toLowerCase()})`)
                    .style('opacity', 0);

                // Calculate label position (midpoint of arrow)
                const midX = (srcNode.x + dstNode.x) / 2;
                const midY = (srcNode.y + dstNode.y) / 2;

                // Create label
                const label = this.messageLayer.append('text')
                    .attr('class', 'message-label')
                    .attr('x', midX)
                    .attr('y', midY - 8)
                    .attr('text-anchor', 'middle')
                    .text(msg.type)
                    .style('opacity', 0);

                // Animate in with delay
                setTimeout(() => {
                    line.transition()
                        .duration(300)
                        .style('opacity', msg.dropped ? 0.4 : 1);

                    label.transition()
                        .duration(300)
                        .style('opacity', msg.dropped ? 0.4 : 1);
                }, delay);

                // Fade out and remove
                setTimeout(() => {
                    line.transition()
                        .duration(500)
                        .style('opacity', 0)
                        .remove();

                    label.transition()
                        .duration(500)
                        .style('opacity', 0)
                        .remove();
                }, delay + persistDuration);
            });
        });
    }

    getNodePosition(uid) {
        const node = this.nodes.find(n => n.uid === uid);
        return node ? { x: node.x, y: node.y } : null;
    }
}

// Export
window.BullyGraph = BullyGraph;
