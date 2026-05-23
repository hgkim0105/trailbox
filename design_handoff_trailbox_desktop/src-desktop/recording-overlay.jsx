// ============================================================
// Recording overlay — small floating REC widget
// (the always-on-top widget shown during recording)
// ============================================================
const { useState: useStateOv, useEffect: useEffectOv } = React;

function TbdRecordingOverlay() {
  const [elapsed, setElapsed] = useStateOv(127);
  useEffectOv(() => {
    const id = setInterval(() => setElapsed(e => e + 1), 1000);
    return () => clearInterval(id);
  }, []);
  const h = Math.floor(elapsed / 3600);
  const m = Math.floor((elapsed % 3600) / 60);
  const s = Math.floor(elapsed % 60);
  const time = h
    ? `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
    : `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;

  return (
    <div style={{
      width: '100%', height: '100%',
      // Mock desktop background to show overlay context
      background: 'linear-gradient(135deg, oklch(0.18 0.04 240), oklch(0.12 0.02 220))',
      position: 'relative',
      overflow: 'hidden',
      padding: 16,
    }}>
      {/* Mock game/app behind it */}
      <div style={{
        position: 'absolute', inset: 16,
        background: 'oklch(0.18 0.04 240)',
        borderRadius: 4,
        overflow: 'hidden',
      }}>
        {/* Fake game HUD */}
        <div style={{ position: 'absolute', top: 12, left: 12, color: 'white', fontFamily: 'Geist Mono', fontSize: 11, opacity: 0.85 }}>
          <div style={{ fontWeight: 600 }}>AURORA · level_07</div>
          <div style={{ fontSize: 9, opacity: 0.6, marginTop: 2 }}>build 412 · 60fps</div>
        </div>
        <div style={{ position: 'absolute', top: '40%', left: '50%', transform: 'translate(-50%, -50%)', width: 120, height: 120, background: 'radial-gradient(closest-side, oklch(0.7 0.18 60 / 0.3), transparent)' }} />
        <div style={{ position: 'absolute', bottom: 16, left: '50%', transform: 'translateX(-50%)', display: 'flex', gap: 4 }}>
          {[1,2,3,4,5].map(n => (
            <div key={n} style={{
              width: 22, height: 22,
              background: n === 2 ? 'oklch(0.55 0.18 282)' : 'oklch(0.2 0 0 / 0.6)',
              border: '1px solid oklch(0.6 0 0 / 0.3)',
              borderRadius: 3,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              color: 'white', fontSize: 9, fontFamily: 'Geist Mono', fontWeight: 600,
            }}>{n}</div>
          ))}
        </div>
      </div>

      {/* The overlay itself — positioned top-right corner */}
      <div style={{
        position: 'absolute',
        top: 28, right: 28,
      }}>
        <div className="tbd-rec-overlay">
          <span className="dot" />
          <span className="time">{time}</span>
          <span className="hint"><kbd>Ctrl+Alt+R</kbd>정지</span>
        </div>
      </div>

      {/* Caption */}
      <div style={{
        position: 'absolute', bottom: 16, left: 16, right: 16,
        textAlign: 'center', color: 'oklch(0.85 0 0)', fontSize: 11,
        background: 'oklch(0 0 0 / 0.5)', padding: '6px 10px',
        borderRadius: 4, backdropFilter: 'blur(4px)',
      }}>
        풀스크린 게임 위에 떠 있는 작은 위젯 · 클릭/입력은 그대로 게임에 전달됨 (click-through)
      </div>
    </div>
  );
}

window.TbdRecordingOverlay = TbdRecordingOverlay;
