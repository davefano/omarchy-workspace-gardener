import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Hyprland
import Quickshell.Wayland
import "Model.js" as Model

Item {
    id: root
    property var shell: null
    readonly property var lockService: shell ? shell.serviceFor("omarchy.lock") : null
    readonly property bool locked: lockService ? lockService.locked : true
    readonly property string stateDir: (Quickshell.env("XDG_STATE_HOME") || Quickshell.env("HOME") + "/.local/state") + "/omarchy/gardener"
    property var usageData: null
    property int focusedId: 0
    property string focusedMonitor: ""
    property var specials: ({})
    property bool ready: false
    property bool frozen: false
    property bool counting: false
    property string error: ""
    property string transaction: ""

    ElapsedTimer { id: elapsed }

    function settle() {
        var ms = elapsed.restartMs();
        if (ready) Model.account(usageData, focusedId, ms, Date.now(), counting);
    }
    function updateCounting() {
        counting = ready && !frozen && !locked && !idle.isIdle && focusedId > 0 && !specials[focusedMonitor];
    }
    function persist() {
        if (!ready) return;
        stateFile.setText(JSON.stringify(usageData));
    }
    function boundary() {
        settle();
        updateCounting();
        if (!counting) persist();
    }
    onLockedChanged: boundary()

    function receive(event) {
        if (!ready || frozen) return;
        var name = String(event.name);
        if (["workspacev2", "focusedmonv2", "activespecialv2", "destroyworkspacev2", "createworkspacev2"].indexOf(name) < 0) return;
        var parts = String(event.data).split(",");
        settle();
        if (name === "workspacev2") focusedId = Number(parts[0]);
        if (name === "focusedmonv2") { focusedMonitor = parts[0]; focusedId = Number(parts[1]); }
        if (name === "activespecialv2") specials[parts[2]] = Number(parts[0]) !== 0;
        if (name === "destroyworkspacev2" || name === "createworkspacev2") delete usageData.seconds[parts[0]];
        updateCounting();
    }
    Connections {
        target: Hyprland
        function onRawEvent(event) { root.receive(event); }
    }
    IdleMonitor {
        id: idle
        enabled: root.ready
        timeout: 120
        respectInhibitors: false
        onIsIdleChanged: root.boundary()
    }
    Timer {
        interval: 60000
        repeat: true
        running: root.counting
        onTriggered: { root.settle(); root.persist(); }
    }
    // A killed CLI must not leave accounting paused forever. Keep the journal
    // for explicit recovery rather than guessing at a half-finished renumber.
    Timer {
        id: lease
        interval: 120000
        onTriggered: { root.error = "Cleanup interrupted; run gardener recover."; root.persist(); }
    }
    FileView {
        id: stateFile
        path: root.stateDir + "/state.json"
        blockLoading: true
        blockWrites: true
        atomicWrites: true
        printErrors: false
        onSaveFailed: { root.error = "Could not save workspace usage."; }
    }
    Process {
        id: bootstrap
        command: ["python3", decodeURIComponent(Qt.resolvedUrl("gardener.py").toString().replace("file://", "")), "snapshot"]
        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    var snapshot = JSON.parse(text);
                    var raw = null;
                    try { raw = JSON.parse(stateFile.text()); } catch (_) {}
                    root.usageData = Model.restore(raw, snapshot.instance, snapshot.workspaces.map(function(w) { return w.id; }), Date.now());
                    snapshot.monitors.forEach(function(m) {
                        root.specials[m.name] = m.specialWorkspace.id !== 0;
                        if (m.focused) { root.focusedId = m.activeWorkspace.id; root.focusedMonitor = m.name; }
                    });
                    root.frozen = snapshot.interrupted;
                    if (root.frozen) root.error = "Cleanup interrupted; run gardener recover.";
                    elapsed.restartMs();
                    root.ready = true;
                    root.updateCounting();
                } catch (e) { root.error = "Could not initialize Gardener: " + e; }
            }
        }
    }
    Component.onCompleted: { elapsed.restartMs(); bootstrap.running = true; }
    Component.onDestruction: { settle(); persist(); }

    IpcHandler {
        target: "gardener"
        function status(): string {
            root.settle();
            return JSON.stringify({ready: root.ready, frozen: root.frozen, counting: root.counting, error: root.error, state: root.usageData});
        }
        function freeze(token: string): string {
            if (!root.ready || root.frozen || root.locked || root.error) return JSON.stringify({error: root.error || "Gardener is busy or the screen is locked."});
            root.settle(); root.frozen = true; root.transaction = token; root.updateCounting(); root.persist(); lease.restart();
            return JSON.stringify({state: root.usageData});
        }
        function finish(token: string, mappingJson: string): string {
            if (!root.frozen || token !== root.transaction) return "invalid transaction";
            var mapping = JSON.parse(mappingJson);
            Model.remap(root.usageData, mapping);
            root.focusedId = Number(mapping[String(root.focusedId)] || root.focusedId);
            root.persist(); lease.stop();
            // Stay paused until the shell restart rebuilds its workspace model.
            return root.error || "ok";
        }
        function cancel(token: string): string {
            if (token !== root.transaction) return "invalid transaction";
            root.settle(); root.frozen = false; root.transaction = ""; lease.stop(); root.updateCounting();
            return "ok";
        }
        function restore(stateJson: string): string {
            if (!root.frozen || root.locked) return "Recovery requires paused tracking and an unlocked screen.";
            var restored = JSON.parse(stateJson);
            if (restored.instance !== root.usageData.instance || restored.version !== 1) return "invalid state";
            root.error = ""; root.usageData = restored; root.persist(); lease.stop();
            return root.error || "ok";
        }
    }
}
