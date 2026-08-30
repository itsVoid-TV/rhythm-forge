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

  function launch() {
    Quickshell.execDetached([root.launcherPath])
  }

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  IpcHandler {
    target: "io.github.itsvoid-tv.rhythm-forge"
    function open(): void { root.launch() }
    function show(): void { root.launch() }
    function toggle(): void { root.launch() }
  }

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: "\uf001"
    slotSize: Style.bar.statusSlot
    fontSize: Style.font.body
    tooltipText: "Open Rhythm Forge"
    onPressed: root.launch()
  }
}
