// ============================================================
// Session detail — Metadata + embedded viewer + share mgmt
// ============================================================
const { useState: useStateSD, useMemo: useMemoSD, useRef: useRefSD, useEffect: useEffectSD } = React;

function SessionDetailScreen({ session, setRoute, openSession, deleteSession }) {
  const I = window.Icons;
  const T = window.TrailboxData;
  const { formatDuration, formatSize, formatNumber } = window;

  const [tab, setTab] = useStateSD('viewer');
  const [playing, setPlaying] = useStateSD(false);
  const [scrub, setScrub] = useStateSD(0.15); // 0..1
  const [eventFilter, setEventFilter] = useStateSD('all'); // all | log | input | error
  const [newShare, setNewShare] = useStateSD(null);
  const [copied, copy] = window.useCopy();
  const [shares, setShares] = useStateSD(session.shares);

  // Auto-advance scrub while "playing"
  useEffectSD(() => {
    if (!playing) return;
    const id = setInterval(() => {
      setScrub(s => {
        const next = s + 0.005;
        if (next >= 1) { setPlaying(false); return 1; }
        return next;
      });
    }, 80);
    return () => clearInterval(id);
  }, [playing]);

  const currentT = scrub * session.duration_seconds;

  // Mock metrics
  const cpuData = useMemoSD(() => T.makeSparkline(session.thumb_seed + 1, 80, [12, 92]), [session]);
  const gpuData = useMemoSD(() => T.makeSparkline(session.thumb_seed + 2, 80, [20, 78]), [session]);
  const ramData = useMemoSD(() => T.makeSparkline(session.thumb_seed + 3, 80, [40, 65]), [session]);
  const vramData = useMemoSD(() => T.makeSparkline(session.thumb_seed + 4, 80, [55, 85]), [session]);
  const fpsData = useMemoSD(() => T.makeSparkline(session.thumb_seed + 5, 80, [45, 60]), [session]);

  const sampleIdx = Math.min(79, Math.floor(scrub * 80));

  // Filter events
  const events = useMemoSD(() => {
    return T.SAMPLE_EVENTS.filter(e => eventFilter === 'all' || e.kind === eventFilter);
  }, [eventFilter]);

  const eventCounts = useMemoSD(() => {
    const c = { all: T.SAMPLE_EVENTS.length, log: 0, input: 0, error: 0, warn: 0 };
    T.SAMPLE_EVENTS.forEach(e => { c[e.kind] = (c[e.kind] || 0) + 1; });
    return c;
  }, []);

  const issueShare = () => {
    const token = Math.random().toString(36).slice(2, 12);
    setNewShare(token);
    setShares(prev => [...prev, { token, created_at: '방금' }]);
    copy(`https://hub.team/v/${token}/`, 'new');
  };

  const revokeShare = (token) => {
    setShares(prev => prev.filter(s => s.token !== token));
  };

  return (
    <div className="content content--wide">
      {/* Header */}
      <div className="detail-header">
        <a href="#" onClick={(e) => { e.preventDefault(); setRoute('sessions'); }}
           style={{ color: 'var(--muted)', display: 'inline-flex', alignItems: 'center', gap: 4 }}>
          <I.Chevron width={12} height={12} style={{ transform: 'rotate(180deg)' }} /> 세션
        </a>
        <span style={{ color: 'var(--subtle)' }}>/</span>
        <span className="detail-id">{session.session_id}</span>
        {session.device === 'PC'
          ? <window.Badge tone="info"><I.PC width={11} height={11} />{session.device_label}</window.Badge>
          : <window.Badge tone="success"><I.Phone width={11} height={11} />{session.device_label}</window.Badge>}
        {(session.tags || []).map(t => (
          <window.Badge key={t} tone="outline">#{t}</window.Badge>
        ))}

        <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
          <window.Button icon={<I.Download />}>zip 다운로드</window.Button>
          <window.Button icon={<I.Share />} variant="primary" onClick={issueShare}>공유 링크 발급</window.Button>
        </div>
      </div>

      {newShare && (
        <window.Flash tone="success" icon={<I.Check />}
          title="공유 링크가 발급되었습니다">
          <code style={{ background: 'oklch(0.55 0.14 150 / 0.1)', padding: '1px 6px', borderRadius: 4 }}>
            https://hub.team/v/{newShare}/
          </code>
          <span style={{ marginLeft: 8, color: 'var(--muted)' }}>· {copied === 'new' ? '✓ 클립보드에 복사됨' : '복사하려면 클릭'}</span>
        </window.Flash>
      )}

      <div className="detail-grid">
        {/* ── Left column: Viewer ── */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <ViewerMock
            session={session}
            playing={playing} setPlaying={setPlaying}
            scrub={scrub} setScrub={setScrub}
          />

          {/* Sub-tabs: events / system / shares */}
          <div className="card">
            <div className="card__header" style={{ paddingBottom: 0, borderBottom: 0 }}>
              <div className="tabs" style={{ marginBottom: 0, borderBottom: 0 }}>
                <div className={`tabs__item ${tab === 'viewer' ? 'active' : ''}`} onClick={() => setTab('viewer')}>이벤트 타임라인<span className="count">{T.SAMPLE_EVENTS.length}</span></div>
                <div className={`tabs__item ${tab === 'system' ? 'active' : ''}`} onClick={() => setTab('system')}>시스템 사양</div>
                <div className={`tabs__item ${tab === 'shares' ? 'active' : ''}`} onClick={() => setTab('shares')}>공유 링크 <span className="count">{shares.length}</span></div>
                <div className={`tabs__item ${tab === 'ai' ? 'active' : ''}`} onClick={() => setTab('ai')}>AI 분석</div>
              </div>
            </div>

            {tab === 'viewer' && (
              <div>
                <div style={{ padding: '12px 18px', borderBottom: '1px solid var(--border)', borderTop: '1px solid var(--border)', display: 'flex', alignItems: 'center', gap: 8 }}>
                  <window.Segmented value={eventFilter} onChange={setEventFilter} options={[
                    { value: 'all', label: `전체 · ${eventCounts.all}` },
                    { value: 'log', label: `Logs · ${eventCounts.log}` },
                    { value: 'input', label: `Inputs · ${eventCounts.input}` },
                    { value: 'error', label: `Errors · ${eventCounts.error}` },
                    { value: 'warn', label: `Warn · ${eventCounts.warn || 0}` },
                  ]} />
                  <div className="input-wrap" style={{ flex: 1, maxWidth: 260, marginLeft: 'auto' }}>
                    <I.Search className="icon-left" />
                    <input className="input" placeholder="이벤트 검색" />
                  </div>
                </div>
                <div className="event-list">
                  {events.map((e, i) => (
                    <div key={i} className="event-row" data-kind={e.kind} onClick={() => setScrub(e.t / session.duration_seconds)}>
                      <span className="event-row__t">
                        <span className="event-row__type" />
                        {formatT(e.t)}
                      </span>
                      <span className="event-row__msg">{e.msg}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {tab === 'system' && (
              <div className="card__body">
                <dl className="kv">
                  <dt>OS</dt><dd>{T.SAMPLE_SYSTEM.os}</dd>
                  <dt>CPU</dt><dd>{T.SAMPLE_SYSTEM.cpu}</dd>
                  <dt>RAM</dt><dd>{T.SAMPLE_SYSTEM.ram}</dd>
                  <dt>GPU</dt><dd>{T.SAMPLE_SYSTEM.gpu}</dd>
                  <dt>VRAM</dt><dd>{T.SAMPLE_SYSTEM.vram}</dd>
                  <dt>Display</dt><dd>{T.SAMPLE_SYSTEM.display}</dd>
                  <dt>Python</dt><dd className="mono">{T.SAMPLE_SYSTEM.python}</dd>
                  <dt>Trailbox</dt><dd className="mono">{T.SAMPLE_SYSTEM.trailbox}</dd>
                  <dt>EXE</dt><dd className="mono">{session.exe_path}</dd>
                </dl>
              </div>
            )}

            {tab === 'shares' && (
              <div className="card__body">
                {shares.length === 0 ? (
                  <div className="empty" style={{ padding: 24 }}>
                    <I.Link width={28} height={28} style={{ opacity: 0.4 }} />
                    <h3>아직 공유 링크가 없습니다</h3>
                    <p>상단의 「공유 링크 발급」 버튼으로 만들 수 있어요.</p>
                  </div>
                ) : (
                  <table className="table">
                    <thead>
                      <tr><th>Token</th><th>URL</th><th>발급</th><th></th></tr>
                    </thead>
                    <tbody>
                      {shares.map(s => (
                        <tr key={s.token}>
                          <td><code>{s.token.slice(0, 8)}…</code></td>
                          <td>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                              <code style={{ flex: 1 }}>https://hub.team/v/{s.token}/</code>
                              <window.Button size="sm" variant="ghost" iconOnly icon={<I.Copy />}
                                onClick={() => copy(`https://hub.team/v/${s.token}/`, s.token)} />
                              {copied === s.token && <window.Badge tone="success" dot>복사됨</window.Badge>}
                            </div>
                          </td>
                          <td>{s.created_at}</td>
                          <td>
                            <window.Button size="sm" variant="ghost" icon={<I.Trash />} onClick={() => revokeShare(s.token)}>
                              revoke
                            </window.Button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            )}

            {tab === 'ai' && (
              <div className="card__body">
                <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12, padding: '4px 0 16px' }}>
                  <div style={{
                    width: 36, height: 36, borderRadius: 10,
                    background: 'var(--accent-soft)', color: 'var(--accent-fg)',
                    display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
                  }}>
                    <I.Robot width={18} height={18} />
                  </div>
                  <div>
                    <div style={{ fontSize: 13.5, fontWeight: 600, marginBottom: 2 }}>Claude · session.analyze</div>
                    <div style={{ fontSize: 12, color: 'var(--muted)' }}>MCP가 영상·로그·입력·메트릭을 검토하고 작성</div>
                  </div>
                  <window.Button size="sm" variant="ghost" icon={<I.Bolt />} style={{ marginLeft: 'auto' }}>재분석</window.Button>
                </div>

                <div style={{ background: 'var(--bg-2)', border: '1px solid var(--border)', borderRadius: 8, padding: 14, fontSize: 13, lineHeight: 1.6, color: 'var(--fg-2)' }}>
                  <p style={{ margin: '0 0 10px' }}><strong style={{ color: 'var(--fg)' }}>요약 ─</strong> Aurora build 412에서 약 5분 32초 길이의 게임플레이 세션. <strong style={{ color: 'var(--danger)' }}>00:34.5에서 GPU device hang 1회</strong>가 기록됐고 즉시 복구되었지만 동일 시점에 RAM 사용량이 8.2GB까지 급격히 상승. 이후 18~25초 구간에서 allocator pressure 경고가 3회 발생.</p>
                  <p style={{ margin: '0 0 10px' }}><strong style={{ color: 'var(--fg)' }}>주목할 만한 구간 ─</strong></p>
                  <ul style={{ margin: '0 0 10px', paddingLeft: 20 }}>
                    <li><code style={{ fontSize: 11 }}>00:18 ~ 00:25</code> · allocator pressure → paged tier 진입 (3 events)</li>
                    <li><code style={{ fontSize: 11 }}>00:34.5</code> · GPU device hang · 1 frame skipped</li>
                    <li><code style={{ fontSize: 11 }}>01:28.6</code> · NaN in damage calc (script error, clamped)</li>
                  </ul>
                  <p style={{ margin: 0 }}><strong style={{ color: 'var(--fg)' }}>제안 ─</strong> Build 411과 비교했을 때 동일 구간에서 RAM 사용 패턴이 다름. 메모리 leak 회귀 의심.</p>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* ── Right column: Metadata + Metrics ── */}
        <aside style={{ display: 'flex', flexDirection: 'column', gap: 16, minWidth: 0 }}>

          {/* Live metrics at current playhead */}
          <div className="viewer-panel">
            <div className="viewer-panel__head">
              <span className="viewer-panel__title">메트릭 · t={formatT(currentT)}</span>
              <span className="mono" style={{ fontSize: 11, color: 'var(--muted)' }}>{playing ? '▶ live' : '⏸ paused'}</span>
            </div>
            <MetricRow label="CPU" data={cpuData} idx={sampleIdx} unit="%" color="oklch(0.65 0.18 25)" />
            <MetricRow label="GPU" data={gpuData} idx={sampleIdx} unit="%" color="oklch(0.65 0.18 280)" />
            <MetricRow label="RAM" data={ramData} idx={sampleIdx} unit="GB" color="oklch(0.65 0.18 150)" scale={0.1} />
            <MetricRow label="VRAM" data={vramData} idx={sampleIdx} unit="%" color="oklch(0.65 0.18 60)" />
            <MetricRow label="FPS" data={fpsData} idx={sampleIdx} unit="" color="oklch(0.65 0.18 200)" />
          </div>

          {/* Metadata */}
          <div className="card">
            <div className="card__header"><h3 className="card__title">세션 정보</h3></div>
            <div className="card__body">
              <dl className="kv" style={{ gridTemplateColumns: '90px 1fr', fontSize: 12.5 }}>
                <dt>시작</dt><dd className="mono" style={{ fontSize: 12 }}>{session.started_at}</dd>
                <dt>길이</dt><dd className="mono">{formatDuration(session.duration_seconds)}</dd>
                <dt>크기</dt><dd className="mono">{formatSize(session.size_bytes)}</dd>
                <dt>로그</dt><dd><span className="mono">{formatNumber(session.log_lines)}</span> 줄</dd>
                <dt>입력</dt><dd><span className="mono">{formatNumber(session.input_events)}</span> 이벤트</dd>
                <dt>샘플</dt><dd><span className="mono">{formatNumber(session.metric_samples)}</span></dd>
                <dt>소유자</dt><dd style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <window.Avatar name={session.owner} size="sm" />{session.owner}
                </dd>
              </dl>
            </div>
            <div className="card__footer">
              <window.Button size="sm" variant="danger" icon={<I.Trash />}
                onClick={() => { if (confirm('정말 삭제하시겠습니까?')) deleteSession(session.session_id); }}>
                세션 삭제
              </window.Button>
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}

function MetricRow({ label, data, idx, unit, color, scale = 1 }) {
  const v = data[idx] * scale;
  return (
    <div className="metric-row">
      <span className="metric-row__label">{label}</span>
      <div className="metric-row__sparkline">
        <SparkWithCursor data={data} idx={idx} color={color} />
      </div>
      <span className="metric-row__value">
        {v.toFixed(unit === 'GB' ? 1 : 0)}<span style={{ fontSize: 10, color: 'var(--muted)', marginLeft: 2 }}>{unit}</span>
      </span>
    </div>
  );
}

function SparkWithCursor({ data, idx, color }) {
  const width = 200, height = 24;
  const max = Math.max(...data), min = Math.min(...data);
  const range = max - min || 1;
  const pts = data.map((v, i) => [
    (i / (data.length - 1)) * width,
    height - ((v - min) / range) * (height - 2) - 1,
  ]);
  const d = pts.reduce((acc, [x, y], i) => {
    if (i === 0) return `M${x},${y}`;
    const [px, py] = pts[i - 1];
    const cx = px + (x - px) / 2;
    return acc + ` C${cx},${py} ${cx},${y} ${x},${y}`;
  }, '');
  const cursorX = pts[idx]?.[0] ?? 0;
  const cursorY = pts[idx]?.[1] ?? 0;
  return (
    <svg viewBox={`0 0 ${width} ${height}`} width="100%" height={height} preserveAspectRatio="none" style={{ display: 'block', overflow: 'visible' }}>
      <path d={d} fill="none" stroke={color} strokeWidth="1.3" opacity="0.8" />
      <line x1={cursorX} y1={0} x2={cursorX} y2={height} stroke="var(--accent)" strokeWidth="1" opacity="0.5" />
      <circle cx={cursorX} cy={cursorY} r="2.2" fill={color} />
    </svg>
  );
}

// ── Viewer mock: animates screen + cursor ──
function ViewerMock({ session, playing, setPlaying, scrub, setScrub }) {
  const I = window.Icons;
  const stageRef = useRefSD(null);
  const { formatDuration } = window;
  const currentT = scrub * session.duration_seconds;

  // Cursor position pseudo-anim
  const cursorPos = {
    x: 20 + Math.sin(scrub * 12) * 25 + 30,
    y: 40 + Math.cos(scrub * 8) * 15 + 20,
  };

  const handleScrub = (e) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const pct = (e.clientX - rect.left) / rect.width;
    setScrub(Math.max(0, Math.min(1, pct)));
  };

  // Compute mocked screen content based on session kind
  const stageContent = session.thumb_kind === 'mobile' ? <MobileStage scrub={scrub} /> : <DesktopStage scrub={scrub} session={session} />;

  return (
    <div className="viewer">
      <div className="viewer__stage" ref={stageRef}>
        <div className="viewer__stage-content">
          {stageContent}
        </div>
        {/* fake cursor */}
        <svg className="viewer__cursor" viewBox="0 0 16 16" style={{ left: `${cursorPos.x}%`, top: `${cursorPos.y}%` }}>
          <path d="M2 2l4.5 11 2-4.5 4.5-2z" fill="white" stroke="black" strokeWidth="0.8" strokeLinejoin="round" />
        </svg>
      </div>
      <div className="viewer__controls">
        <button className="btn btn--icon btn--sm"><I.SkipBack /></button>
        <button className="btn btn--icon btn--sm" onClick={() => setPlaying(p => !p)}>
          {playing ? <I.Pause /> : <I.Play />}
        </button>
        <button className="btn btn--icon btn--sm"><I.SkipFwd /></button>
        <span className="viewer__time">{formatT(currentT)} / {window.formatDuration(session.duration_seconds)}</span>
        <div className="viewer__scrub" onClick={handleScrub}>
          <div className="viewer__scrub-fill" style={{ width: `${scrub * 100}%` }} />
          <div className="viewer__scrub-handle" style={{ left: `${scrub * 100}%` }} />
        </div>
        <button className="btn btn--icon btn--sm" title="배속 1×">1×</button>
      </div>
    </div>
  );
}

function DesktopStage({ scrub, session }) {
  // Mock game UI
  const phase = scrub * 4;
  return (
    <div style={{ position: 'absolute', inset: 0, background: 'linear-gradient(160deg, oklch(0.3 0.12 280), oklch(0.18 0.05 240))', overflow: 'hidden' }}>
      {/* environment gradients */}
      <div style={{ position: 'absolute', top: '40%', left: `${20 + scrub * 30}%`, width: '40%', height: '40%', background: 'radial-gradient(closest-side, oklch(0.7 0.18 60 / 0.5), transparent)' }} />
      <div style={{ position: 'absolute', top: '20%', left: `${60 - scrub * 20}%`, width: '30%', height: '30%', background: 'radial-gradient(closest-side, oklch(0.7 0.18 280 / 0.4), transparent)' }} />

      {/* HUD top */}
      <div style={{ position: 'absolute', top: 12, left: 12, color: 'white', fontFamily: 'Geist Mono', fontSize: 12 }}>
        <div style={{ fontWeight: 600, marginBottom: 2 }}>AURORA · build 412</div>
        <div style={{ fontSize: 10, opacity: 0.7 }}>level_07 · pack_alpha_03</div>
      </div>

      {/* Health bar */}
      <div style={{ position: 'absolute', top: 16, right: 16, display: 'flex', flexDirection: 'column', gap: 4, alignItems: 'flex-end' }}>
        <div style={{ width: 120, height: 6, background: 'oklch(0.2 0 0 / 0.5)', borderRadius: 999 }}>
          <div style={{ width: `${Math.max(15, 100 - scrub * 60)}%`, height: '100%', background: 'oklch(0.65 0.18 25)', borderRadius: 999 }} />
        </div>
        <div style={{ width: 90, height: 4, background: 'oklch(0.2 0 0 / 0.5)', borderRadius: 999 }}>
          <div style={{ width: `${Math.max(20, 100 - scrub * 40)}%`, height: '100%', background: 'oklch(0.65 0.18 240)', borderRadius: 999 }} />
        </div>
      </div>

      {/* Character silhouette */}
      <div style={{
        position: 'absolute', bottom: '20%', left: '50%',
        width: 80, height: 130,
        transform: `translateX(${-50 + Math.sin(phase) * 5}%)`,
        background: 'radial-gradient(closest-side, oklch(0.45 0.1 240), transparent)',
        filter: 'blur(2px)',
      }} />

      {/* Ground */}
      <div style={{ position: 'absolute', bottom: 0, left: 0, right: 0, height: '20%', background: 'linear-gradient(180deg, oklch(0.2 0.04 200 / 0.6), oklch(0.1 0.02 200))' }} />

      {/* Action bar */}
      <div style={{ position: 'absolute', bottom: 12, left: '50%', transform: 'translateX(-50%)', display: 'flex', gap: 4 }}>
        {[1,2,3,4,5].map(n => (
          <div key={n} style={{
            width: 28, height: 28,
            background: n === Math.floor(scrub * 5) + 1 ? 'oklch(0.55 0.18 282)' : 'oklch(0.2 0 0 / 0.6)',
            border: '1px solid oklch(0.6 0 0 / 0.3)',
            borderRadius: 4,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            color: 'white', fontSize: 10, fontFamily: 'Geist Mono', fontWeight: 600,
          }}>{n}</div>
        ))}
      </div>

      {/* Minimap */}
      <div style={{ position: 'absolute', bottom: 12, right: 12, width: 80, height: 80, background: 'oklch(0.15 0.02 200 / 0.7)', border: '1px solid oklch(0.6 0 0 / 0.2)', borderRadius: 6 }}>
        <div style={{ position: 'absolute', left: `${30 + scrub * 30}%`, top: `${40 - scrub * 10}%`, width: 4, height: 4, background: 'oklch(0.7 0.18 60)', borderRadius: '50%', boxShadow: '0 0 6px oklch(0.7 0.18 60)' }} />
      </div>
    </div>
  );
}

function MobileStage({ scrub }) {
  return (
    <div style={{ position: 'absolute', inset: 0, background: 'oklch(0.2 0.02 220)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div style={{
        width: 200, height: '85%',
        background: 'oklch(0.13 0.02 220)', borderRadius: 18,
        border: '4px solid oklch(0.3 0.01 220)',
        position: 'relative',
        boxShadow: '0 20px 40px oklch(0 0 0 / 0.6)',
        overflow: 'hidden',
      }}>
        {/* Status bar */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px 14px', color: 'white', fontSize: 10, fontFamily: 'Geist Mono' }}>
          <span>9:41</span>
          <span style={{ display: 'flex', gap: 4 }}>5G ◉</span>
        </div>
        {/* App content */}
        <div style={{ padding: 12, background: 'white', height: 'calc(100% - 30px)', display: 'flex', flexDirection: 'column', gap: 8 }}>
          <div style={{ height: 24, background: 'oklch(0.55 0.18 282)', borderRadius: 6, display: 'flex', alignItems: 'center', padding: '0 8px', color: 'white', fontSize: 9, fontWeight: 600 }}>Shopper</div>
          <div style={{ height: 60, background: `linear-gradient(${scrub * 360}deg, oklch(0.85 0.1 ${scrub * 360}), oklch(0.7 0.15 ${(scrub * 360 + 60) % 360}))`, borderRadius: 6 }} />
          <div style={{ height: 12, background: 'oklch(0.95 0 0)', borderRadius: 3, width: '80%' }} />
          <div style={{ height: 8, background: 'oklch(0.93 0 0)', borderRadius: 3, width: '60%' }} />
          <div style={{ display: 'flex', gap: 4 }}>
            <div style={{ flex: 1, height: 40, background: 'oklch(0.97 0 0)', borderRadius: 4 }} />
            <div style={{ flex: 1, height: 40, background: 'oklch(0.97 0 0)', borderRadius: 4 }} />
          </div>
          <div style={{ marginTop: 'auto', height: 32, background: scrub > 0.5 ? 'oklch(0.55 0.18 150)' : 'oklch(0.55 0.18 282)', borderRadius: 16, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'white', fontSize: 10, fontWeight: 600 }}>
            {scrub > 0.5 ? '결제 완료' : '결제하기'}
          </div>
        </div>
      </div>
    </div>
  );
}

function formatT(t) {
  const s = Math.floor(t % 60);
  const m = Math.floor(t / 60);
  const ms = Math.floor((t - Math.floor(t)) * 10);
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}.${ms}`;
}

window.SessionDetailScreen = SessionDetailScreen;
