import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

BarWidget {
  id: root
  moduleName: "io.github.itsvoid-tv.rhythm-forge"

  readonly property string launcherPath: decodeURIComponent(
    Qt.resolvedUrl("app/rhythm-forge").toString().replace(/^file:\/\//, "")
  )
  readonly property string dependencyCheckerPath: decodeURIComponent(
    Qt.resolvedUrl("app/check-dependencies").toString().replace(/^file:\/\//, "")
  )
  property bool dependenciesChecked: false
  property bool dependenciesReady: false
  property bool launchWhenReady: false
  property bool dependencyCheckTimedOut: false
  property string dependencyMessage: "Checking Rhythm Forge dependencies…"

  function launch() {
    if (root.dependenciesChecked && root.dependenciesReady) {
      Quickshell.execDetached([root.launcherPath])
      return
    }
    root.checkDependencies(true)
  }

  function checkDependencies(thenLaunch) {
    root.launchWhenReady = root.launchWhenReady || thenLaunch
    if (dependencyCheck.running) return
    root.dependencyCheckTimedOut = false
    root.dependencyMessage = "Checking Rhythm Forge dependencies…"
    dependencyCheck.running = true
    dependencyCheckWatchdog.restart()
  }

  function finishDependencyCheck(exitCode, output) {
    dependencyCheckWatchdog.stop()
    if (root.dependencyCheckTimedOut) {
      root.dependencyCheckTimedOut = false
      return
    }
    root.dependenciesChecked = true
    root.dependenciesReady = exitCode === 0
    var message = String(output || "").replace(/\s+/g, " ").trim().slice(0, 500)
    root.dependencyMessage = message || (root.dependenciesReady
      ? "Rhythm Forge is ready."
      : "Rhythm Forge dependencies could not be checked.")
    if (root.launchWhenReady) {
      if (root.dependenciesReady) Quickshell.execDetached([root.launcherPath])
      else Quickshell.execDetached([root.dependencyCheckerPath, "--notify"])
    }
    root.launchWhenReady = false
  }

  Component.onCompleted: root.checkDependencies(false)

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  IpcHandler {
    target: "io.github.itsvoid-tv.rhythm-forge"
    function open(): void { root.launch() }
    function show(): void { root.launch() }
    function toggle(): void { root.launch() }
  }

  Process {
    id: dependencyCheck
    running: false
    command: [root.dependencyCheckerPath]
    stdout: StdioCollector { id: dependencyStdout; waitForEnd: true }
    stderr: StdioCollector { id: dependencyStderr; waitForEnd: true }
    onExited: function(exitCode) {
      var output = String(dependencyStdout.text || dependencyStderr.text || "")
      root.finishDependencyCheck(exitCode, output)
    }
  }

  Timer {
    id: dependencyCheckWatchdog
    interval: 7000
    repeat: false
    onTriggered: {
      root.dependencyCheckTimedOut = true
      dependencyCheck.running = false
      root.dependenciesChecked = true
      root.dependenciesReady = false
      root.dependencyMessage = "Dependency check timed out. Click to retry."
      root.launchWhenReady = false
    }
  }

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: root.dependenciesChecked && !root.dependenciesReady ? "\uf071" : "\uf001"
    slotSize: Style.bar.statusSlot
    fontSize: Style.font.body
    tooltipText: root.dependenciesChecked && root.dependenciesReady
      ? "Open Rhythm Forge"
      : root.dependencyMessage
    onPressed: root.launch()
  }
}
