pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtMultimedia
import QtCore

ApplicationWindow {
    id: root
    visible: true
    visibility: Window.Maximized
    minimumWidth: 760
    minimumHeight: 520
    title: "Rhythm Forge"
    color: "#090b13"

    property var notes: []
    property int nextNote: 0
    property int score: 0
    property int combo: 0
    property int maxCombo: 0
    property int judged: 0
    property real accuracyTotal: 0
    property int offsetMs: 0
    property string trackTitle: ""
    property string trackArtist: ""
    property string judgement: "LOADING VIDEO"
    property color judgementColor: "#f4f5fb"
    property bool gameReady: false
    property bool finished: false
    property bool paused: false
    property string playbackError: ""
    property var startupArguments: Qt.application.arguments
    property string trackKey: "default"
    property url settingsUri: ""
    property bool vsyncEnabled: true
    property int overhits: 0
    property double lastPressAt: -1000
    property bool spaceHeld: false
    property bool holdActive: false
    property var holdStartResult: null
    property int spamHits: 0
    property real spamFirstDelta: 0
    property int spamBonusTaps: 0
    property int spamBonusScore: 0
    property bool mediaPrepared: false
    property bool countdownActive: false
    property int countdownValue: 3
    property int songStarRating: 0
    property int starsEarned: 0
    property bool eventPrepared: false
    property bool eventIntroVisible: false
    property bool eventWon: false
    property string eventOutcome: ""
    property var activeEvent: ({ "active": false })
    property var exclusiveRewards: [
        { "category": "spam", "id": "eventAurora", "name": "Event Aurora", "color": "#2dffe2" },
        { "category": "hold", "id": "eventCrimson", "name": "Event Crimson", "color": "#ff315f" },
        { "category": "lane", "id": "eventSolar", "name": "Event Solar", "color": "#ff9d2d" }
    ]
    property var colorCatalog: ({
        "spamDefault": "#ffb83f", "spamBlue": "#4d9cff", "spamPink": "#ff5fd2", "spamGreen": "#58e38c", "spamPurple": "#aa70ff", "spamWhite": "#f4f5fb", "spamRed": "#ff5c6f", "eventAurora": "#2dffe2",
        "holdDefault": "#70edc2", "holdRed": "#ff526f", "holdGold": "#ffc857", "holdBlue": "#4d9cff", "holdPurple": "#b477ff", "holdWhite": "#f4f5fb", "holdOrange": "#ff9d45", "eventCrimson": "#ff315f",
        "laneDefault": "#8a70ff", "laneYellow": "#ffe14d", "laneIce": "#62d9ff", "laneGreen": "#5ee6a8", "laneRed": "#ff5a70", "laneWhite": "#f4f5fb", "lanePink": "#ff70c8", "eventSolar": "#ff9d2d"
    })
    property var heldHitKeys: ({})
    property int holdInputKey: 0

    readonly property real accuracy: judged > 0 ? accuracyTotal / judged * 100 : 100
    readonly property color spamColor: colorCatalog[progressionSettings.equippedSpam] || colorCatalog.spamDefault
    readonly property color holdColor: colorCatalog[progressionSettings.equippedHold] || colorCatalog.holdDefault
    readonly property color laneColor: colorCatalog[progressionSettings.equippedLane] || colorCatalog.laneDefault

    function loadSession() {
        // The launcher passes six values after `--`. Reading from the end is
        // stable across qml runner versions, which prepend different internal
        // arguments to Qt.application.arguments.
        if (startupArguments.length < 6) {
            playbackError = "The game did not receive its track data."
            return
        }
        var base = startupArguments.length - 6
        try {
            root.notes = JSON.parse(startupArguments[base + 1])
            root.trackTitle = startupArguments[base + 2] || "Untitled track"
            root.trackArtist = startupArguments[base + 3] || "Unknown artist"
            root.trackKey = startupArguments[base + 4] || "default"
            root.settingsUri = startupArguments[base + 5]
            player.source = startupArguments[base]
            console.log("Rhythm Forge opening", player.source, "with", root.notes.length, "note blocks")
            restoreOffset.restart()
        } catch (error) {
            root.playbackError = "Invalid track data: " + error
        }
    }

    function timingLabel(delta) {
        var distance = Math.abs(delta)
        if (distance <= 70) return ["PERFECT", 1000, 1.0, "#ad9cff"]
        if (distance <= 130) return ["GREAT", 650, 0.75, "#70edc2"]
        if (distance <= 200) return ["GOOD", 350, 0.45, "#f5d875"]
        return null
    }

    function registerHit(result) {
        judged += 1
        if (!result) {
            combo = 0
            judgement = "MISS"
            judgementColor = "#ff718d"
            return
        }
        combo += 1
        maxCombo = Math.max(maxCombo, combo)
        score += Math.round(result[1] * (1.0 + Math.min(1.0, combo / 50.0)))
        accuracyTotal += result[2]
        judgement = result[0]
        judgementColor = result[3]
    }

    function registerOverhit() {
        overhits += 1
    }

    function ownedString(category) {
        if (category === "spam") return progressionSettings.ownedSpam
        if (category === "hold") return progressionSettings.ownedHold
        return progressionSettings.ownedLane
    }

    function isOwned(category, colorId) {
        return ownedString(category).indexOf("|" + colorId + "|") >= 0
    }

    function equippedColor(category) {
        if (category === "spam") return progressionSettings.equippedSpam
        if (category === "hold") return progressionSettings.equippedHold
        return progressionSettings.equippedLane
    }

    function addOwned(category, colorId) {
        if (isOwned(category, colorId)) return
        if (category === "spam") progressionSettings.ownedSpam += colorId + "|"
        else if (category === "hold") progressionSettings.ownedHold += colorId + "|"
        else progressionSettings.ownedLane += colorId + "|"
    }

    function calculateSongStars() {
        if (accuracy < 50) return 0
        var durationMinutes = Math.max(1, Math.ceil(player.duration / 60000))
        var lengthStars = Math.min(4, durationMinutes)
        var skillStars = 1
        if (accuracy >= 98) skillStars = 6
        else if (accuracy >= 93) skillStars = 5
        else if (accuracy >= 85) skillStars = 4
        else if (accuracy >= 75) skillStars = 3
        else if (accuracy >= 65) skillStars = 2
        return Math.min(10, lengthStars + skillStars)
    }

    function prepareEvent() {
        if (eventPrepared) return
        eventPrepared = true
        var locked = []
        for (var index = 0; index < exclusiveRewards.length; ++index) {
            var reward = exclusiveRewards[index]
            if (!isOwned(reward.category, reward.id)) locked.push(reward)
        }
        if (locked.length === 0 || Math.random() >= 0.05) {
            activeEvent = { "active": false }
            return
        }
        var selected = locked[Math.floor(Math.random() * locked.length)]
        var target = notes.length >= 300 ? 500000 : (notes.length >= 150 ? 250000 : 100000)
        activeEvent = {
            "active": true,
            "category": selected.category,
            "id": selected.id,
            "name": selected.name,
            "color": selected.color,
            "target": target
        }
    }

    function startCountdown() {
        eventIntroVisible = false
        countdownActive = true
        countdownValue = 3
        judgement = "3"
        judgementColor = "#f4f5fb"
        countdownTimer.start()
        keyCatcher.forceActiveFocus()
    }

    function beginPreSong() {
        if (!mediaPrepared || !eventPrepared) return
        player.pause()
        player.position = 0
        if (activeEvent.active) {
            countdownActive = false
            eventIntroVisible = true
            judgement = "EVENT!"
        } else {
            startCountdown()
        }
    }

    function awardSpamBonus() {
        var points = Math.round(125 * (1.0 + Math.min(1.0, combo / 50.0)))
        score += points
        spamBonusTaps += 1
        spamBonusScore += points
        return points
    }

    function acceptPress(wallTime) {
        // Filter only impossible duplicate events/switch chatter. Deliberate
        // rapid tapping stays fully playable for dense song sections.
        if (wallTime - lastPressAt < 20) return false
        lastPressAt = wallTime
        return true
    }

    function finishNote(result) {
        registerHit(result)
        nextNote += 1
        spamHits = 0
        spamFirstDelta = 0
        holdActive = false
        holdStartResult = null
    }

    function pressHitKey(key) {
        if (heldHitKeys[key]) return
        heldHitKeys[key] = true
        var wasHolding = holdActive
        pressSpace()
        if (!wasHolding && holdActive) holdInputKey = key
    }

    function releaseHitKey(key) {
        if (!heldHitKeys[key]) return
        heldHitKeys[key] = false
        if (holdActive && holdInputKey === key) {
            spaceHeld = true
            releaseSpace()
            holdInputKey = 0
        }
    }

    function pressSpace() {
        if (!gameReady || paused || finished || countdownActive) return
        if (!acceptPress(Date.now())) return
        spaceHeld = true
        var now = player.position + offsetMs
        if (nextNote >= notes.length) {
            registerOverhit()
            return
        }
        var note = notes[nextNote]
        var delta = now - note.start * 1000
        if (note.type === "spam") {
            if (now < note.start * 1000 - 200 || now > note.end * 1000 + 200) {
                registerOverhit()
            } else {
                if (spamHits === 0) spamFirstDelta = delta
                spamHits += 1
                if (spamHits > note.taps && now <= note.end * 1000) {
                    var bonus = awardSpamBonus()
                    judgement = "SPAM BONUS  +" + bonus
                } else {
                    judgement = "SPAM  " + Math.min(spamHits, note.taps) + " / " + note.taps
                }
                judgementColor = "#ffcf67"
            }
        } else if (note.type === "hold") {
            if (Math.abs(delta) <= 200 && !holdActive) {
                holdActive = true
                holdStartResult = timingLabel(delta)
                judgement = "HOLD"
                judgementColor = "#70edc2"
            } else {
                registerOverhit()
            }
        } else if (Math.abs(delta) <= 200) {
            finishNote(timingLabel(delta))
        } else {
            registerOverhit()
        }
        judgementFade.restart()
        playfield.requestPaint()
    }

    function releaseSpace() {
        if (!spaceHeld) return
        spaceHeld = false
        if (!holdActive || nextNote >= notes.length) return
        var note = notes[nextNote]
        var now = player.position + offsetMs
        if (now >= note.end * 1000 - 200) finishNote(holdStartResult)
        else finishNote(null)
        judgement = now >= note.end * 1000 - 200 ? "HOLD COMPLETE" : "RELEASED EARLY"
        judgementColor = now >= note.end * 1000 - 200 ? "#70edc2" : "#ff718d"
        judgementFade.restart()
        playfield.requestPaint()
    }

    function markMisses() {
        if (!gameReady || paused || finished) return
        var now = player.position + offsetMs
        var changed = false
        while (nextNote < notes.length) {
            var note = notes[nextNote]
            if (note.type === "hold" && holdActive) {
                if (now >= note.end * 1000) {
                    finishNote(holdStartResult)
                    judgement = "HOLD COMPLETE"
                    judgementColor = "#70edc2"
                    changed = true
                    continue
                }
                break
            }
            var deadline = (note.type === "spam" ? note.end : note.start) * 1000 + 200
            if (now <= deadline) break
            if (note.type === "spam" && spamHits >= note.taps) {
                finishNote(timingLabel(spamFirstDelta))
                judgement = "SPAM COMPLETE"
                judgementColor = "#ffcf67"
            } else {
                finishNote(null)
                judgement = "MISS"
                judgementColor = "#ff718d"
            }
            changed = true
        }
        if (changed) judgementFade.restart()
    }

    function togglePause() {
        if (!gameReady || finished || eventIntroVisible) return
        paused = !paused
        if (paused) player.pause()
        else player.play()
        judgement = paused ? "PAUSED" : ""
        judgementColor = "#f4f5fb"
    }

    function adjustOffset(delta) {
        offsetMs = Math.max(-250, Math.min(250, offsetMs + delta))
        timingSettings.songOffsetMs = offsetMs
        playfield.requestPaint()
    }

    function resetOffset() {
        offsetMs = 0
        timingSettings.songOffsetMs = 0
        playfield.requestPaint()
    }

    function setVSync(enabled) {
        vsyncEnabled = enabled
        displaySettings.savedVSync = enabled
        playfield.requestPaint()
    }

    function advanceFrame() {
        root.markMisses()
        playfield.requestPaint()
    }

    function completeGame() {
        if (finished) return
        while (nextNote < notes.length) {
            registerHit(null)
            nextNote += 1
        }
        songStarRating = calculateSongStars()
        starsEarned = Math.max(0, songStarRating - timingSettings.bestStars)
        if (starsEarned > 0) {
            progressionSettings.stars += starsEarned
            progressionSettings.lifetimeStars += starsEarned
            timingSettings.bestStars = songStarRating
        }
        progressionSettings.songsCompleted += 1
        if (activeEvent.active) {
            if (score >= activeEvent.target) {
                addOwned(activeEvent.category, activeEvent.id)
                progressionSettings.eventWins += 1
                eventWon = true
                eventOutcome = "EVENT WON · " + activeEvent.name + " UNLOCKED"
            } else {
                eventOutcome = "EVENT MISSED · Needed " + activeEvent.target.toLocaleString(Qt.locale("en_US"), "f", 0) + " points"
            }
        }
        finished = true
        gameReady = false
        resultCard.visible = true
    }

    Component.onCompleted: {
        keyCatcher.forceActiveFocus()
        loadSession()
    }

    Settings {
        id: timingSettings
        location: root.settingsUri
        category: "track-" + root.trackKey
        property int songOffsetMs: 0
        property int bestStars: 0
    }

    Settings {
        id: displaySettings
        location: root.settingsUri
        category: "display"
        property bool savedVSync: true
    }

    Settings {
        id: progressionSettings
        location: root.settingsUri
        category: "progression"
        property int stars: 0
        property int lifetimeStars: 0
        property int songsCompleted: 0
        property int eventWins: 0
        property string ownedSpam: "|spamDefault|"
        property string ownedHold: "|holdDefault|"
        property string ownedLane: "|laneDefault|"
        property string equippedSpam: "spamDefault"
        property string equippedHold: "holdDefault"
        property string equippedLane: "laneDefault"
    }

    Timer {
        id: restoreOffset
        interval: 50
        repeat: false
        onTriggered: {
            root.offsetMs = timingSettings.songOffsetMs
            root.vsyncEnabled = displaySettings.savedVSync
            root.prepareEvent()
            root.beginPreSong()
        }
    }

    MediaPlayer {
        id: player
        audioOutput: AudioOutput { volume: 1.0; muted: false }
        videoOutput: videoOutput
        onMediaStatusChanged: {
            console.log("Rhythm Forge media status", mediaStatus, "position", position, "error", errorString)
            if ((mediaStatus === MediaPlayer.LoadedMedia || mediaStatus === MediaPlayer.BufferedMedia) && !root.mediaPrepared) {
                root.mediaPrepared = true
                root.gameReady = false
                player.pause()
                player.position = 0
                root.beginPreSong()
            } else if (mediaStatus === MediaPlayer.EndOfMedia) {
                root.completeGame()
            } else if (mediaStatus === MediaPlayer.InvalidMedia) {
                root.playbackError = errorString || "Qt Multimedia could not decode this video."
            }
        }
        onErrorOccurred: function(error, errorString) {
            root.playbackError = errorString || "The video could not be played."
        }
    }

    Timer {
        id: countdownTimer
        interval: 1000
        repeat: true
        onTriggered: {
            if (root.countdownValue > 1) {
                root.countdownValue -= 1
                root.judgement = String(root.countdownValue)
            } else {
                stop()
                root.countdownValue = 0
                root.countdownActive = false
                root.gameReady = true
                root.judgement = "GO!"
                root.judgementColor = "#70edc2"
                player.play()
                goFade.restart()
                keyCatcher.forceActiveFocus()
            }
        }
    }

    VideoOutput {
        id: videoOutput
        anchors.fill: parent
        fillMode: VideoOutput.PreserveAspectCrop
    }

    Rectangle {
        anchors.fill: parent
        color: "#50090b13"
    }

    Canvas {
        id: playfield
        anchors.fill: parent
        onPaint: {
            var ctx = getContext("2d")
            ctx.reset()
            var laneWidth = Math.max(160, Math.min(280, width * 0.23))
            var centerX = width / 2
            var targetY = height * 0.79
            var spawnY = 45
            var approach = 1700
            ctx.fillStyle = "#78080a12"
            ctx.fillRect(centerX - laneWidth / 2, 0, laneWidth, height)
            ctx.globalAlpha = 0.58
            ctx.fillStyle = root.laneColor
            ctx.fillRect(centerX - laneWidth / 2, targetY - 8, laneWidth, 16)
            ctx.globalAlpha = 1.0
            ctx.fillStyle = root.laneColor
            ctx.fillRect(centerX - laneWidth / 2, targetY - 2, laneWidth, 4)

            var now = player.position + root.offsetMs
            function noteY(timeMs) {
                var remaining = timeMs - now
                var progress = 1 - Math.max(0, remaining) / approach
                return spawnY + (targetY - spawnY) * progress
            }
            for (var index = root.nextNote; index < root.notes.length; ++index) {
                var note = root.notes[index]
                var startRemaining = note.start * 1000 - now
                var endRemaining = note.end * 1000 - now
                if (startRemaining > approach) break
                if (endRemaining < -200) continue
                var y = noteY(note.start * 1000)
                var noteWidth = laneWidth * 0.78
                if (note.type === "spam" || note.type === "hold") {
                    var endY = noteY(note.end * 1000)
                    var top = Math.min(y, endY)
                    var bottom = Math.max(y, endY)
                    var blockHeight = Math.max(36, bottom - top + 22)
                    var blockY = top - 11
                    ctx.globalAlpha = 0.42
                    ctx.fillStyle = note.type === "spam" ? root.spamColor : root.holdColor
                    ctx.fillRect(centerX - noteWidth / 2 - 7, blockY - 7, noteWidth + 14, blockHeight + 14)
                    ctx.globalAlpha = 0.94
                    ctx.fillStyle = note.type === "spam" ? root.spamColor : root.holdColor
                    ctx.fillRect(centerX - noteWidth / 2, blockY, noteWidth, blockHeight)
                    ctx.globalAlpha = 1.0
                    ctx.fillStyle = "#ff111522"
                    ctx.font = "bold 19px sans-serif"
                    ctx.textAlign = "center"
                    ctx.textBaseline = "middle"
                    ctx.fillText(note.type === "spam" ? "SPAM" : "HOLD", centerX, blockY + blockHeight / 2)
                } else {
                    ctx.fillStyle = "#6f8668ff"
                    ctx.fillRect(centerX - noteWidth / 2 - 7, y - 14, noteWidth + 14, 28)
                    ctx.fillStyle = "#ffe1d9ff"
                    ctx.fillRect(centerX - noteWidth / 2, y - 7, noteWidth, 14)
                }
            }
            ctx.fillStyle = "#f0ffffff"
            ctx.font = "bold 17px sans-serif"
            ctx.textAlign = "center"
            ctx.textBaseline = "alphabetic"
            ctx.fillText("SPACE  /  W  /  ↑", centerX, targetY + 49)
        }
    }

    FrameAnimation {
        running: root.vsyncEnabled && root.gameReady && !root.paused && !root.finished
        onTriggered: root.advanceFrame()
    }

    Timer {
        interval: 16
        running: !root.vsyncEnabled && root.gameReady && !root.paused && !root.finished
        repeat: true
        onTriggered: root.advanceFrame()
    }

    Timer {
        interval: 10000
        running: !root.mediaPrepared && !root.finished && root.playbackError === ""
        repeat: false
        onTriggered: root.playbackError = "The video did not start within 10 seconds. Close this window and try the track again."
    }

    NumberAnimation {
        id: judgementFade
        target: judgementText
        property: "opacity"
        from: 1
        to: 0
        duration: 650
    }

    NumberAnimation {
        id: goFade
        target: judgementText
        property: "opacity"
        from: 1
        to: 0
        duration: 700
    }

    RowLayout {
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.margins: 24
        spacing: 30

        Stat { caption: "SCORE"; value: root.score.toLocaleString(Qt.locale("en_US"), "f", 0) }
        Stat { caption: "COMBO"; value: String(root.combo) }
        Stat { caption: "ACCURACY"; value: root.accuracy.toFixed(1) + "%" }
        Item { Layout.fillWidth: true }
        Label { text: "★ " + progressionSettings.stars; color: "#ffe14d"; font.bold: true; font.pixelSize: 18 }
        Switch {
            text: "VSync"
            focusPolicy: Qt.NoFocus
            checked: root.vsyncEnabled
            onToggled: {
                root.setVSync(checked)
                keyCatcher.forceActiveFocus()
            }
            ToolTip.text: checked ? "Notes update on every rendered frame" : "Notes use the 60 Hz fallback timer"
            ToolTip.visible: hovered
        }
        Label {
            text: "SYNC  " + (root.offsetMs >= 0 ? "+" : "") + root.offsetMs + " ms"
            color: "#d8dbee"
            font.bold: true
            padding: 10
            background: Rectangle { color: "#cc05070d"; radius: 10 }
        }
        Button { text: "−10"; focusPolicy: Qt.NoFocus; onClicked: root.adjustOffset(-10); ToolTip.text: "Move notes later"; ToolTip.visible: hovered }
        Button { text: "+10"; focusPolicy: Qt.NoFocus; onClicked: root.adjustOffset(10); ToolTip.text: "Move notes earlier"; ToolTip.visible: hovered }
        Button { text: "Reset"; focusPolicy: Qt.NoFocus; onClicked: root.resetOffset() }
        Button { text: root.paused ? "Resume" : "Pause"; focusPolicy: Qt.NoFocus; onClicked: root.togglePause() }
        Button { text: "Close"; focusPolicy: Qt.NoFocus; onClicked: root.close() }
    }

    Label {
        id: judgementText
        anchors.centerIn: parent
        text: root.judgement
        color: root.judgementColor
        font.pixelSize: 42
        font.bold: true
        style: Text.Outline
        styleColor: "#aa000000"
    }

    Column {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 24
        spacing: 6
        Label {
            anchors.horizontalCenter: parent.horizontalCenter
            text: root.trackTitle + "  —  " + root.trackArtist
            color: "#e8eaf4"
            padding: 10
            background: Rectangle { color: "#cc05070d"; radius: 10 }
        }
        Label {
            anchors.horizontalCenter: parent.horizontalCenter
            text: "[ notes later  ·  ] notes earlier  ·  sync is saved for this song"
            color: "#c4c8da"
            font.pixelSize: 12
            padding: 7
            background: Rectangle { color: "#bb05070d"; radius: 8 }
        }
    }

    Rectangle {
        anchors.fill: parent
        visible: root.playbackError !== ""
        color: "#dd090b13"
        Column {
            anchors.centerIn: parent
            spacing: 16
            width: Math.min(620, parent.width - 60)
            Label { text: "PLAYBACK ERROR"; color: "#ff8096"; font.pixelSize: 34; font.bold: true; anchors.horizontalCenter: parent.horizontalCenter }
            Label { text: root.playbackError; color: "white"; wrapMode: Text.Wrap; width: parent.width; horizontalAlignment: Text.AlignHCenter }
            Button { text: "Close"; focusPolicy: Qt.NoFocus; anchors.horizontalCenter: parent.horizontalCenter; onClicked: root.close() }
        }
    }

    Rectangle {
        id: resultCard
        visible: false
        z: 20
        anchors.centerIn: parent
        width: 500
        height: root.activeEvent.active ? 500 : 450
        radius: 20
        color: "#f0191c2b"
        border.color: "#708a70ff"
        Column {
            anchors.centerIn: parent
            spacing: 12
            Label { text: "TRACK COMPLETE"; color: "white"; font.pixelSize: 30; font.bold: true; anchors.horizontalCenter: parent.horizontalCenter }
            Label { text: "Score  " + root.score.toLocaleString(Qt.locale("en_US"), "f", 0); color: "white"; anchors.horizontalCenter: parent.horizontalCenter }
            Label { text: "Accuracy  " + root.accuracy.toFixed(1) + "%"; color: "white"; anchors.horizontalCenter: parent.horizontalCenter }
            Label { text: "Max combo  " + root.maxCombo; color: "white"; anchors.horizontalCenter: parent.horizontalCenter }
            Label {
                text: "Song rating  ★" + root.songStarRating + " / 10  ·  Earned +" + root.starsEarned
                color: "#ffe14d"
                font.bold: true
                anchors.horizontalCenter: parent.horizontalCenter
            }
            Label { text: "SPAM bonus taps  " + root.spamBonusTaps; color: "#ffcf67"; anchors.horizontalCenter: parent.horizontalCenter }
            Label { text: "SPAM bonus points  +" + root.spamBonusScore.toLocaleString(Qt.locale("en_US"), "f", 0); color: "#ffcf67"; anchors.horizontalCenter: parent.horizontalCenter }
            Label { text: "Extra taps  " + root.overhits; color: "#c4c8da"; anchors.horizontalCenter: parent.horizontalCenter }
            Label {
                visible: root.activeEvent.active
                text: root.eventOutcome
                color: root.eventWon ? "#2dffe2" : "#ff718d"
                font.bold: true
                anchors.horizontalCenter: parent.horizontalCenter
            }
            Button { text: "Close"; focusPolicy: Qt.NoFocus; anchors.horizontalCenter: parent.horizontalCenter; onClicked: root.close() }
        }
    }

    Rectangle {
        id: eventIntro
        visible: root.eventIntroVisible
        z: 90
        anchors.fill: parent
        color: "#e6090b13"
        Rectangle {
            anchors.centerIn: parent
            width: Math.min(620, parent.width - 60)
            height: 390
            radius: 24
            color: "#f0191c2b"
            border.width: 2
            border.color: root.activeEvent.color || "#ffe14d"
            Column {
                anchors.centerIn: parent
                width: parent.width - 70
                spacing: 18
                Label { text: "RANDOM EVENT"; color: "#ffe14d"; font.pixelSize: 18; font.bold: true; anchors.horizontalCenter: parent.horizontalCenter }
                Label { text: "A rare challenge appeared!"; color: "white"; font.pixelSize: 30; font.bold: true; anchors.horizontalCenter: parent.horizontalCenter }
                Label {
                    text: "Score " + Number(root.activeEvent.target || 0).toLocaleString(Qt.locale("en_US"), "f", 0) + " points in this song."
                    color: "#e8eaf4"
                    font.pixelSize: 20
                    anchors.horizontalCenter: parent.horizontalCenter
                }
                Row {
                    anchors.horizontalCenter: parent.horizontalCenter
                    spacing: 14
                    Rectangle { width: 36; height: 36; radius: 8; color: root.activeEvent.color || "#ffe14d" }
                    Label { text: "Reward: " + (root.activeEvent.name || "Exclusive Color"); color: root.activeEvent.color || "#ffe14d"; font.pixelSize: 20; font.bold: true; anchors.verticalCenter: parent.verticalCenter }
                }
                Label { text: "Event colors cannot be purchased on the song-selection shop."; color: "#aeb4ca"; anchors.horizontalCenter: parent.horizontalCenter }
                Button {
                    text: "Start Event Challenge"
                    focusPolicy: Qt.NoFocus
                    anchors.horizontalCenter: parent.horizontalCenter
                    onClicked: root.startCountdown()
                }
            }
        }
    }

    Item {
        id: keyCatcher
        anchors.fill: parent
        focus: true
        Keys.onPressed: function(event) {
            if (event.key === Qt.Key_Space || event.key === Qt.Key_W || event.key === Qt.Key_Up) {
                if (!event.isAutoRepeat) root.pressHitKey(event.key)
                event.accepted = true
            }
        }
        Keys.onReleased: function(event) {
            if (event.key === Qt.Key_Space || event.key === Qt.Key_W || event.key === Qt.Key_Up) {
                if (!event.isAutoRepeat) root.releaseHitKey(event.key)
                event.accepted = true
            }
        }
    }
    Shortcut { sequence: "P"; autoRepeat: false; onActivated: root.togglePause() }
    Shortcut { sequence: "Escape"; autoRepeat: false; onActivated: root.togglePause() }
    Shortcut { sequence: "["; autoRepeat: false; onActivated: root.adjustOffset(-10) }
    Shortcut { sequence: "]"; autoRepeat: false; onActivated: root.adjustOffset(10) }

    component Stat: Column {
        required property string caption
        required property string value
        Label { text: parent.value; color: "white"; font.pixelSize: 24; font.bold: true }
        Label { text: parent.caption; color: "#bec3d7"; font.pixelSize: 11; font.bold: true; font.letterSpacing: 2 }
    }

}
