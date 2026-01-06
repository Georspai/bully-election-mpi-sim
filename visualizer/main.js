// main.js - Main application logic

class BullyVisualizer {
    constructor() {
        this.parser = new LogParser();
        this.graph = null;
        this.timeline = null;
        this.currentTick = 0;
        this.maxTick = 0;
        this.isPlaying = false;
        this.playInterval = null;
        this.playSpeed = 1000; // Slower default for educational purposes

        this.stateFileLoaded = false;
        this.msgFileLoaded = false;
        this.debugFileLoaded = false;

        this.setupEventListeners();
        this.setupKeyboardShortcuts();
    }

    setupKeyboardShortcuts() {
        document.addEventListener('keydown', (e) => {
            // Ignore key events when typing in inputs/textareas
            const tag = document.activeElement.tagName;
            if (tag === 'INPUT' || tag === 'TEXTAREA') return;

            switch (e.key) {
                case 'ArrowRight':
                    e.preventDefault();
                    this.nextTick();
                    break;

                case 'ArrowLeft':
                    e.preventDefault();
                    this.prevTick();
                    break;

                case ' ':
                    e.preventDefault();
                    this.togglePlay();
                    break;
            }
        });
    }

    setupEventListeners() {
        // File inputs
        document.getElementById('state-file').addEventListener('change', (e) => {
            this.handleStateFile(e.target.files[0]);
        });

        document.getElementById('msg-file').addEventListener('change', (e) => {
            this.handleMessageFile(e.target.files[0]);
        });

        document.getElementById('load-btn').addEventListener('click', () => {
            this.initializeVisualization();
        });

        // Playback controls
        document.getElementById('play-btn').addEventListener('click', () => {
            this.togglePlay();
        });

        document.getElementById('prev-btn').addEventListener('click', () => {
            this.prevTick();
        });

        document.getElementById('next-btn').addEventListener('click', () => {
            this.nextTick();
        });

        document.getElementById('step-btn').addEventListener('click', () => {
            this.step();
        });

        document.getElementById('reset-btn').addEventListener('click', () => {
            this.reset();
        });

        // Timeline slider
        document.getElementById('tick-slider').addEventListener('input', (e) => {
            this.goToTick(parseInt(e.target.value));
        });

        // Speed control
        document.getElementById('speed-slider').addEventListener('input', (e) => {
            this.playSpeed = parseInt(e.target.value);
            document.getElementById('speed-display').textContent = `${this.playSpeed}ms`;

            // If playing, restart with new speed
            if (this.isPlaying) {
                this.stopPlay();
                this.startPlay();
            }
        });
    }

    handleStateFile(file) {
        if (!file) return;

        const reader = new FileReader();
        reader.onload = (e) => {
            this.parser.parseStateLogs(e.target.result);
            this.stateFileLoaded = true;
            this.checkFilesLoaded();
        };
        reader.readAsText(file);
    }

    handleMessageFile(file) {
        if (!file) return;

        const reader = new FileReader();
        reader.onload = (e) => {
            this.parser.parseMessageLogs(e.target.result);
            this.msgFileLoaded = true;
            this.checkFilesLoaded();
        };
        reader.readAsText(file);
    }

    checkFilesLoaded() {
        const loadBtn = document.getElementById('load-btn');
        loadBtn.disabled = !(this.stateFileLoaded && this.msgFileLoaded);
    }

    async autoLoadFiles(stateFile, messageFile, debugFile) {
        try {
            // Fetch state log
            const stateResponse = await fetch(stateFile);
            const stateText = await stateResponse.text();
            this.parser.parseStateLogs(stateText);
            this.stateFileLoaded = true;

            // Fetch message log
            const msgResponse = await fetch(messageFile);
            const msgText = await msgResponse.text();
            this.parser.parseMessageLogs(msgText);
            this.msgFileLoaded = true;

            // Fetch debug log (optional)
            if (debugFile) {
                try {
                    const debugResponse = await fetch(debugFile);
                    const debugText = await debugResponse.text();
                    this.parser.parseDebugLogs(debugText);
                    this.debugFileLoaded = true;
                } catch (e) {
                    console.warn('Debug log not found or failed to load:', e);
                }
            }

            // Update UI to show files are loaded
            document.getElementById('load-btn').disabled = false;
            document.getElementById('load-btn').textContent = 'Files Loaded - Click to Visualize';

            // Auto-initialize
            this.initializeVisualization();
        } catch (error) {
            console.error('Failed to auto-load files:', error);
        }
    }

    initializeVisualization() {
        const metadata = this.parser.getMetadata();
        const nodeUIDs = this.parser.getNodeUIDs();
        this.maxTick = this.parser.getMaxTick();

        // Update metadata display
        if (metadata) {
            document.getElementById('num-nodes').textContent = metadata.numNodes;
            document.getElementById('num-ticks').textContent = metadata.numTicks;
            document.getElementById('seed').textContent = metadata.seed;
        }

        // Initialize graph
        this.graph = new BullyGraph('#graph');
        this.graph.initNodes(nodeUIDs);

        // Initialize state timeline
        this.timeline = new StateTimeline('#timeline-chart', this.parser);
        this.timeline.init(nodeUIDs, this.maxTick);
        this.timeline.setTickClickHandler((tick) => {
            this.goToTick(tick);
        });

        // Setup timeline slider
        const slider = document.getElementById('tick-slider');
        slider.max = this.maxTick;
        slider.disabled = false;

        // Update speed display to match default
        document.getElementById('speed-slider').value = this.playSpeed;
        document.getElementById('speed-display').textContent = `${this.playSpeed}ms`;

        // Enable controls
        document.getElementById('play-btn').disabled = false;
        document.getElementById('prev-btn').disabled = false;
        document.getElementById('next-btn').disabled = false;
        document.getElementById('step-btn').disabled = false;
        document.getElementById('reset-btn').disabled = false;

        // Show initial state
        this.goToTick(0);
    }

    goToTick(tick) {
        this.currentTick = Math.max(0, Math.min(tick, this.maxTick));

        // Update slider
        document.getElementById('tick-slider').value = this.currentTick;
        document.getElementById('tick-display').textContent = `${this.currentTick} / ${this.maxTick}`;
        document.getElementById('current-tick').textContent = this.currentTick;

        // Get state, messages, and debug info for this tick
        const state = this.parser.getStateAtTick(this.currentTick);
        const messages = this.parser.getMessagesAtTick(this.currentTick);
        const debugMessages = this.parser.getDebugAtTick(this.currentTick);

        // Update graph
        if (this.graph) {
            const leaderUid = this.graph.updateState(state);
            this.graph.showMessages(messages);
            this.graph.setDebugMessages(debugMessages);

            // Update info panel
            document.getElementById('current-leader').textContent = leaderUid || '-';

            const electionsActive = state.filter(n => n.election).length;
            document.getElementById('elections-active').textContent = electionsActive;

            const nodesOnline = state.filter(n => n.online).length;
            document.getElementById('nodes-online').textContent = `${nodesOnline} / ${state.length}`;
        }

        // Update timeline indicator
        if (this.timeline) {
            this.timeline.updateTickIndicator(this.currentTick);
        }

        // Update message log
        this.updateMessageLog(messages);
    }

    updateMessageLog(messages) {
        const logContent = document.getElementById('message-log-content');

        // Filter to show only sends (not receives) to avoid duplicates
        const sentMessages = messages.filter(m => m.direction === 'send');

        if (sentMessages.length === 0) {
            logContent.innerHTML = '<div class="msg-entry" style="color: var(--text-muted); font-style: italic;">No messages this tick</div>';
            return;
        }

        const html = sentMessages.map(msg => {
            const typeClass = msg.type.toLowerCase();
            const dstText = msg.dst === -1 ? 'ALL' : `Node ${msg.dst}`;
            const droppedTag = msg.dropped ? '<span class="msg-dropped">[DROPPED]</span>' : '';

            return `<div class="msg-entry ${msg.dropped ? 'dropped' : ''}">
                <span class="msg-type ${typeClass}">${msg.type}</span>
                <span class="msg-route">Node ${msg.src} → ${dstText}</span>
                ${droppedTag}
            </div>`;
        }).join('');

        logContent.innerHTML = html;
    }

    nextTick() {
        if (this.currentTick < this.maxTick) {
            this.goToTick(this.currentTick + 1);
        }
    }

    prevTick() {
        if (this.currentTick > 0) {
            this.goToTick(this.currentTick - 1);
        }
    }

    step() {
        // Pause if playing, then advance one tick
        if (this.isPlaying) {
            this.stopPlay();
        }
        this.nextTick();
    }

    reset() {
        // Stop playback and go to beginning
        if (this.isPlaying) {
            this.stopPlay();
        }
        this.goToTick(0);
    }

    togglePlay() {
        if (this.isPlaying) {
            this.stopPlay();
        } else {
            this.startPlay();
        }
    }

    startPlay() {
        this.isPlaying = true;
        document.getElementById('play-btn').innerHTML = '&#10074;&#10074; Pause';

        this.playInterval = setInterval(() => {
            if (this.currentTick >= this.maxTick) {
                this.stopPlay();
                this.goToTick(0); // Loop back to start
            } else {
                this.nextTick();
            }
        }, this.playSpeed);
    }

    stopPlay() {
        this.isPlaying = false;
        document.getElementById('play-btn').innerHTML = '&#9654; Play';

        if (this.playInterval) {
            clearInterval(this.playInterval);
            this.playInterval = null;
        }
    }
}

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    window.visualizer = new BullyVisualizer();

    // Check for autoload config
    fetch('autoload.json')
        .then(response => response.json())
        .then(config => {
            if (config.autoload && config.stateFile && config.messageFile) {
                console.log('Auto-loading log files...');
                window.visualizer.autoLoadFiles(config.stateFile, config.messageFile, config.debugFile);
            }
        })
        .catch(() => {
            // No autoload config, user must upload manually
            console.log('No autoload config found, manual upload required');
        });
});
