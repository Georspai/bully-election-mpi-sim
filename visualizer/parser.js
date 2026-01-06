// parser.js - Parse JSON Lines log files

class LogParser {
    constructor() {
        this.metadata = null;
        this.statesByTick = new Map();
        this.messagesByTick = new Map();
        this.debugByTick = new Map();  // Map<tick, Map<uid, string[]>>
        this.maxTick = 0;
    }

    parseStateLogs(text) {
        const lines = text.trim().split('\n');

        for (const line of lines) {
            if (!line.trim()) continue;

            try {
                const obj = JSON.parse(line);

                if (obj.metadata) {
                    this.metadata = {
                        numNodes: obj.num_nodes,
                        numTicks: obj.num_ticks,
                        seed: obj.seed
                    };
                } else if (obj.tick !== undefined) {
                    this.statesByTick.set(obj.tick, obj.nodes);
                    this.maxTick = Math.max(this.maxTick, obj.tick);
                }
            } catch (e) {
                console.warn('Failed to parse state line:', line, e);
            }
        }
    }

    parseMessageLogs(text) {
        const lines = text.trim().split('\n');

        for (const line of lines) {
            if (!line.trim()) continue;

            try {
                const obj = JSON.parse(line);

                if (obj.tick !== undefined) {
                    if (!this.messagesByTick.has(obj.tick)) {
                        this.messagesByTick.set(obj.tick, []);
                    }
                    this.messagesByTick.get(obj.tick).push({
                        type: obj.type,
                        src: obj.src,
                        dst: obj.dst,
                        dropped: obj.dropped,
                        direction: obj.dir
                    });
                }
            } catch (e) {
                console.warn('Failed to parse message line:', line, e);
            }
        }
    }

    parseDebugLogs(text) {
        const lines = text.trim().split('\n');

        for (const line of lines) {
            if (!line.trim()) continue;

            try {
                const obj = JSON.parse(line);

                if (obj.tick !== undefined && obj.uid !== undefined && obj.msg) {
                    if (!this.debugByTick.has(obj.tick)) {
                        this.debugByTick.set(obj.tick, new Map());
                    }
                    const tickMap = this.debugByTick.get(obj.tick);
                    if (!tickMap.has(obj.uid)) {
                        tickMap.set(obj.uid, []);
                    }
                    tickMap.get(obj.uid).push(obj.msg);
                }
            } catch (e) {
                console.warn('Failed to parse debug line:', line, e);
            }
        }
    }

    getStateAtTick(tick) {
        return this.statesByTick.get(tick) || [];
    }

    getMessagesAtTick(tick) {
        return this.messagesByTick.get(tick) || [];
    }

    getDebugAtTick(tick) {
        return this.debugByTick.get(tick) || new Map();
    }

    getMetadata() {
        return this.metadata;
    }

    getMaxTick() {
        return this.maxTick;
    }

    // Get unique node UIDs from first tick
    getNodeUIDs() {
        const firstState = this.statesByTick.get(0);
        if (!firstState) return [];
        return firstState.map(n => n.uid).sort((a, b) => a - b);
    }
}

// Export for use in other modules
window.LogParser = LogParser;
