// timeline.js - State timeline bar chart for educational visualization

class StateTimeline {
    constructor(containerSelector, parser) {
        this.container = d3.select(containerSelector);
        this.parser = parser;
        this.svg = null;
        this.width = 0;
        this.height = 0;
        this.margin = { top: 20, right: 30, bottom: 30, left: 60 };
        this.currentTick = 0;
        this.onTickClick = null;

        this.colors = {
            online: '#4ade80',
            offline: '#6b7280',
            leader: '#c9a227',
            election: '#ef4444'
        };

        window.addEventListener('resize', () => this.handleResize());
    }

    init(nodeUIDs, maxTick) {
        this.nodeUIDs = nodeUIDs;
        this.maxTick = maxTick;

        // Clear any existing content
        this.container.selectAll('*').remove();

        // Get container dimensions
        const containerNode = this.container.node();
        this.width = containerNode.clientWidth;
        this.height = containerNode.clientHeight;

        // Create SVG
        this.svg = this.container.append('svg')
            .attr('width', this.width)
            .attr('height', this.height);

        // Build all states data for rendering
        this.buildStateData();
        this.render();
    }

    buildStateData() {
        // Pre-compute leader for each tick
        this.stateData = [];

        for (let tick = 0; tick <= this.maxTick; tick++) {
            const states = this.parser.getStateAtTick(tick);

            // Find leader for this tick
            let leaderUid = null;
            states.forEach(s => {
                if (s.online && s.leader === s.uid) {
                    leaderUid = s.uid;
                }
            });

            // If no self-proclaimed leader, find consensus
            if (leaderUid === null) {
                const leaderCounts = new Map();
                states.forEach(s => {
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

            states.forEach(s => {
                this.stateData.push({
                    tick: tick,
                    uid: s.uid,
                    online: s.online,
                    isLeader: s.uid === leaderUid,
                    inElection: s.election
                });
            });
        }
    }

    render() {
        const innerWidth = this.width - this.margin.left - this.margin.right;
        const innerHeight = this.height - this.margin.top - this.margin.bottom;

        // Clear and re-render
        this.svg.selectAll('*').remove();

        // Create main group
        const g = this.svg.append('g')
            .attr('transform', `translate(${this.margin.left}, ${this.margin.top})`);

        // X scale (ticks)
        this.xScale = d3.scaleLinear()
            .domain([0, this.maxTick])
            .range([0, innerWidth]);

        // Y scale (nodes)
        this.yScale = d3.scaleBand()
            .domain(this.nodeUIDs)
            .range([0, innerHeight])
            .padding(0.1);

        // Calculate cell width
        const cellWidth = Math.max(1, innerWidth / (this.maxTick + 1));
        const cellHeight = this.yScale.bandwidth();

        // Draw state cells
        const cells = g.selectAll('.state-cell')
            .data(this.stateData)
            .join('rect')
            .attr('class', 'state-cell')
            .attr('x', d => this.xScale(d.tick))
            .attr('y', d => this.yScale(d.uid))
            .attr('width', cellWidth)
            .attr('height', cellHeight)
            .attr('fill', d => {
                if (!d.online) return this.colors.offline;
                if (d.isLeader) return this.colors.leader;
                return this.colors.online;
            })
            .attr('stroke', d => d.inElection ? this.colors.election : 'none')
            .attr('stroke-width', d => d.inElection ? 2 : 0)
            .style('cursor', 'pointer')
            .on('click', (event, d) => {
                if (this.onTickClick) {
                    this.onTickClick(d.tick);
                }
            });

        // Add X axis
        const xAxis = d3.axisBottom(this.xScale)
            .ticks(Math.min(20, this.maxTick))
            .tickFormat(d => d);

        g.append('g')
            .attr('class', 'x-axis')
            .attr('transform', `translate(0, ${innerHeight})`)
            .call(xAxis);

        // Add Y axis (node UIDs)
        const yAxis = d3.axisLeft(this.yScale)
            .tickFormat(d => `Node ${d}`);

        g.append('g')
            .attr('class', 'y-axis')
            .call(yAxis);

        // Add axis labels
        this.svg.append('text')
            .attr('class', 'axis-label')
            .attr('x', this.width / 2)
            .attr('y', this.height - 5)
            .attr('text-anchor', 'middle')
            .text('Tick');

        // Current tick indicator line
        this.tickIndicator = g.append('line')
            .attr('class', 'tick-indicator')
            .attr('y1', 0)
            .attr('y2', innerHeight)
            .attr('stroke', '#fff')
            .attr('stroke-width', 2)
            .attr('stroke-dasharray', '4,2')
            .attr('opacity', 0.8);

        this.updateTickIndicator(this.currentTick);
    }

    updateTickIndicator(tick) {
        this.currentTick = tick;
        if (this.tickIndicator && this.xScale) {
            const cellWidth = (this.width - this.margin.left - this.margin.right) / (this.maxTick + 1);
            this.tickIndicator.attr('x1', this.xScale(tick) + cellWidth / 2)
                .attr('x2', this.xScale(tick) + cellWidth / 2);
        }
    }

    handleResize() {
        if (!this.nodeUIDs) return;

        const containerNode = this.container.node();
        this.width = containerNode.clientWidth;
        this.height = containerNode.clientHeight;

        this.render();
        this.updateTickIndicator(this.currentTick);
    }

    setTickClickHandler(handler) {
        this.onTickClick = handler;
    }
}

// Export
window.StateTimeline = StateTimeline;
