import { useCallback, useEffect, useRef, useState } from 'react'
import html2canvas from 'html2canvas'
import {
  buildShareText,
  CgExportPortal,
  downloadCgExportCard,
  exportPosterToDataUrl,
} from './ResultShare'

interface AiFeedback {
  is_correct: boolean;
  feedback: string;
  corrected_sentence: string | null;
}

// 🌟 GitHub Raw Assets Base URL - Locked for character consistency
const GITHUB_BASE = "https://raw.githubusercontent.com/mrcatpickles/word-wizard/refs/heads/main/";

const CHARACTER_TAGS: Record<string, string[]> = {
  "Adrien": ["Gentle Elite", "Warm Heart", "Golden Boy"],
  "Richard": ["Sharp CEO", "Intense", "High-Executive"],
  "Damon": ["Wild Heart", "Free Spirit", "Adventurous"],
  "Lucas": ["Mysterious", "Cool", "Cyber-Night"],
  "Fresh Chic": ["Cozy", "Radiant", "Pure"],
  "Night Elegance": ["Sophisticated", "Mystic", "Graceful"],
  "Executive Aura": ["Confident", "Sharp", "Independent"],
  "Grace Classic": ["Vintage", "Elegant", "Timeless"]
};

const PROTAGONIST_PROFILES = {
  "Fresh Chic": "Cinematic portrait of a young woman, cute short bob hair, oversized sweater, soft smooth skin.",
  "Night Elegance": "Cinematic portrait of a young woman, long straight black hair, elegant silk evening gown, soft smooth skin.",
  "Executive Aura": "Cinematic portrait of a young woman, sharp eyes, tailored black blazer, confident office style.",
  "Grace Classic": "Cinematic portrait of a young woman, auburn hair updo, classic chic vintage dress, soft smooth skin."
} as const;

const MALE_LEADS = ['Adrien', 'Richard', 'Damon', 'Lucas'] as const;
type PortraitStyle = 'cinematic' | 'comic';
type AgeGate = 'unknown' | 'adult' | 'minor';

// 与 GitHub 仓库中的实际文件名一致（含空格的会做 URL 编码）
const enc = (s: string) => encodeURIComponent(s);
const CHARACTER_OPTIONS_BY_STYLE: Record<PortraitStyle, Array<{ name: typeof MALE_LEADS[number]; avatar: string }>> = {
  cinematic: [
    { name: 'Adrien', avatar: GITHUB_BASE + enc('Adrien.png') },
    { name: 'Richard', avatar: GITHUB_BASE + enc('Richard.png') },
    { name: 'Damon', avatar: GITHUB_BASE + enc('Damon.png') },
    { name: 'Lucas', avatar: GITHUB_BASE + enc('Lucas.png') }
  ],
  comic: [
    { name: 'Adrien', avatar: GITHUB_BASE + enc('Arien comic.png') },
    { name: 'Richard', avatar: GITHUB_BASE + enc('Richard comic.png') },
    { name: 'Damon', avatar: GITHUB_BASE + enc('Damon comic.png') },
    { name: 'Lucas', avatar: GITHUB_BASE + enc('Lucas comic.png') }
  ]
};

const PROFILE_OPTIONS_BY_STYLE: Record<PortraitStyle, Array<{ name: keyof typeof PROTAGONIST_PROFILES; avatar: string }>> = {
  cinematic: [
    { name: 'Fresh Chic', avatar: GITHUB_BASE + enc('fresh chic.png') },
    { name: 'Night Elegance', avatar: GITHUB_BASE + enc('night elegance.png') },
    { name: 'Executive Aura', avatar: GITHUB_BASE + enc('executive aura.png') },
    { name: 'Grace Classic', avatar: GITHUB_BASE + enc('grace classic.png') }
  ],
  comic: [
    { name: 'Fresh Chic', avatar: GITHUB_BASE + enc('fresh chic-comic.png') },
    { name: 'Night Elegance', avatar: GITHUB_BASE + enc('night elegance comic.png') },
    { name: 'Executive Aura', avatar: GITHUB_BASE + enc('exective aura comic.png') },
    { name: 'Grace Classic', avatar: GITHUB_BASE + enc('Grace Classic comic.png') }
  ]
};

const theme = { bg: '#050505', pink: '#ec4899', pinkDark: '#be185d', pinkLight: '#fbcfe8', border: '#374151' };

/**
 * 开发：走 Vite 代理（同域 /api、/asset），避免直连 8002 被浏览器/扩展拦截导致 Failed to fetch。
 * 生产：设 VITE_API_BASE=https://你的后端域名
 * 若后端不在 8002，在 frontend/.env 写 VITE_DEV_PROXY_TARGET=http://127.0.0.1:8000
 */
const API_BASE = import.meta.env.DEV
  ? ''
  : ((import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, '') || 'http://127.0.0.1:8002');
const BGM_BASE = `${API_BASE}/asset/bgm/`;
const BGM_FILES = [
  'Sam Ock; Michelle - Can I Have the Day With You (feat. Michelle).mp3',
  'Geologic Of The Blue Scholars; Jeff Bernat - Call You Mine (feat. Geologic Of The Blue Scholars).mp3',
  "10cc - I'm Not in Love.mp3",
  'Laufey - Lover Girl.mp3',
  'Jesse Barrera; Michael Carreon; Albert Posis - Maybe We Could Be a Thing.mp3',
]

function shuffle<T>(arr: T[]): T[] {
  const out = [...arr]
  for (let i = out.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1))
    ;[out[i], out[j]] = [out[j], out[i]]
  }
  return out
}

function AvatarImg({ src, alt, fallback }: { src: string; alt: string; fallback: string }) {
  const [failed, setFailed] = useState(false)

  if (failed) {
    return (
      <div
        aria-label={alt}
        title={alt}
        style={{
          width: '100%',
          height: '100%',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          background: 'linear-gradient(135deg, rgba(236,72,153,0.35), rgba(17,24,39,0.85))',
          color: '#fff',
          fontWeight: 800,
          fontSize: '0.85rem',
          letterSpacing: '0.06em',
          textTransform: 'uppercase',
          userSelect: 'none',
        }}
      >
        {fallback}
      </div>
    )
  }

  return (
    <img
      src={src}
      alt={alt}
      style={{ width: '100%', height: '100%', objectFit: 'cover' }}
      onError={() => setFailed(true)}
      loading="lazy"
      referrerPolicy="no-referrer"
    />
  )
}

export default function App() {
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const [bgmEnabled, setBgmEnabled] = useState(true)
  const [showBgmHint, setShowBgmHint] = useState(false)
  const queueRef = useRef<string[]>([])
  const indexRef = useRef(0)
  const lastPlayedUrlRef = useRef<string | null>(null)

  const getNextBgmUrl = useCallback(() => {
    const list = BGM_FILES.filter(Boolean).map((f) => BGM_BASE + encodeURIComponent(f))
    if (list.length === 0) return null
    if (queueRef.current.length === 0 || indexRef.current >= queueRef.current.length) {
      queueRef.current = shuffle(list)
      indexRef.current = 0
      // 新一轮的第一首不能和上一轮最后一首相同，避免连续重复
      const last = lastPlayedUrlRef.current
      if (last && queueRef.current[0] === last && queueRef.current.length > 1) {
        const first = queueRef.current[0]
        queueRef.current[0] = queueRef.current[1]
        queueRef.current[1] = first
      }
    }
    return queueRef.current[indexRef.current++] ?? null
  }, [])

  const [character, setCharacter] = useState<typeof MALE_LEADS[number]>('Adrien');
  const [heroine, setHeroine] = useState<keyof typeof PROTAGONIST_PROFILES>('Night Elegance');
  const [portraitStyle] = useState<PortraitStyle>('cinematic');
  const [currentRound, setCurrentRound] = useState(1);
  const [magicWords, setMagicWords] = useState<string[]>([]);
  const [recentWords, setRecentWords] = useState<string[]>([]);
  const [sentence, setSentence] = useState('');
  const [feedback, setFeedback] = useState<AiFeedback | null>(null);
  const [generatedImageUrl, setGeneratedImageUrl] = useState<string | null>(null);
  const [imageError, setImageError] = useState<string | null>(null);
  const [isLoadingWords, setIsLoadingWords] = useState(true);
  const [isProcessing, setIsProcessing] = useState(false);
  const [isTurnComplete, setIsTurnComplete] = useState(false);
  const [ageGate, setAgeGate] = useState<AgeGate>('unknown');
  const [completedSentences, setCompletedSentences] = useState<string[]>([]);
  const [storyResult, setStoryResult] = useState<{
    story_text: string;
    image_urls: (string | null)[];
    vocabulary: { phrase: string; explanation: string }[];
    sentences: string[];
  } | null>(null);
  const storyContentRef = useRef<HTMLDivElement | null>(null);
  const [showFinalStory, setShowFinalStory] = useState(false);
  const [isGeneratingStory, setIsGeneratingStory] = useState(false);
  const [showPosterLayer, setShowPosterLayer] = useState(false);
  const [posterDataUrl, setPosterDataUrl] = useState<string | null>(null);
  const [isShareSaving, setIsShareSaving] = useState(false);
  const [copyPostHint, setCopyPostHint] = useState<string | null>(null);

  useEffect(() => { fetchMagicWords(1, 3) }, []);

  useEffect(() => {
    const el = audioRef.current
    if (!el) return

    el.volume = 0.35

    if (!bgmEnabled) {
      el.pause()
      el.currentTime = 0
      setShowBgmHint(false)
      return
    }

    const playNext = () => {
      const url = getNextBgmUrl()
      if (!url) return
      lastPlayedUrlRef.current = url
      el.src = url
      el.play().then(() => setShowBgmHint(false)).catch(() => setShowBgmHint(true))
    }

    // 一进来就设好第一首并直接尝试播放；若被浏览器拦截则显示提示
    const firstUrl = getNextBgmUrl()
    if (firstUrl) {
      lastPlayedUrlRef.current = firstUrl
      el.src = firstUrl
      el.load()
      el.play()
        .then(() => setShowBgmHint(false))
        .catch(() => setShowBgmHint(true))
    }

    const onEnded = () => {
      playNext()
    }
    el.addEventListener('ended', onEnded)

    // 自动播放被拦截时，用户点击/按键后再试一次并关闭提示
    const tryPlay = () => {
      if (el.src && el.src !== window.location.href) {
        el.play().then(() => setShowBgmHint(false)).catch(() => {})
        return
      }
      playNext()
    }
    window.addEventListener('pointerdown', tryPlay, { passive: true })
    window.addEventListener('keydown', tryPlay)

    return () => {
      el.removeEventListener('ended', onEnded)
      window.removeEventListener('pointerdown', tryPlay)
      window.removeEventListener('keydown', tryPlay)
    }
  }, [bgmEnabled, getNextBgmUrl])

  const fetchMagicWords = async (roundToSet = currentRound, countToFetch = 3) => {
    setIsLoadingWords(true); setSentence(''); setFeedback(null); setGeneratedImageUrl(null); setImageError(null); setIsTurnComplete(false);
    try {
      const response = await fetch(`${API_BASE}/api/get_words`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          scene: 'Dating',
          character,
          word_count: countToFetch,
          is_adult: ageGate === 'adult',
          recent_words: recentWords,
        })
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        setImageError(
          `拉取单词失败（${response.status}）：${
            typeof data?.detail === 'string'
              ? data.detail
              : '请确认后端已启动。开发模式：cd backend && ./run_dev.sh（默认8002），再重启 npm run dev。'
          }`
        );
        setMagicWords([]);
        return;
      }
      const newWords: string[] = data.words ?? [];
      setMagicWords(newWords);
      setCurrentRound(roundToSet);
      setImageError(null);
      if (newWords.length) {
        setRecentWords(prev => [...prev, ...newWords]);
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      setImageError(
        import.meta.env.DEV
          ? `连不上后端：${msg}。开发模式请：① 终端执行 cd backend && ./run_dev.sh（默认 8002）；② 重启前端 npm run dev；③ 若后端在别的端口，在 frontend/.env 写 VITE_DEV_PROXY_TARGET=http://127.0.0.1:端口 后再 npm run dev。`
          : `连不上后端：${msg}。请配置 VITE_API_BASE 或启动对应 API 服务。`
      );
      setMagicWords([]);
    } finally { setIsLoadingWords(false) }
  };

  const handleSubmitSentence = async () => {
    if (isProcessing) return;
    setIsProcessing(true); setFeedback(null); setImageError(null);
    try {
      const maleAvatar = CHARACTER_OPTIONS_BY_STYLE[portraitStyle].find(o => o.name === character)?.avatar;
      const femaleAvatar = PROFILE_OPTIONS_BY_STYLE[portraitStyle].find(o => o.name === heroine)?.avatar;

      const payload = {
        sentence, required_words: magicWords, scene: 'Dating', character,
        protagonist_profile: PROTAGONIST_PROFILES[heroine],
        portrait_style: portraitStyle,
        male_avatar_url: maleAvatar ?? '',
        female_avatar_url: femaleAvatar ?? '',
        is_adult: ageGate === 'adult',
      };
      const response = await fetch(`${API_BASE}/api/process_turn`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload)
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        setImageError(data?.detail || 'Request failed. Please try again.');
        setGeneratedImageUrl(null);
        setIsTurnComplete(false);
        setIsProcessing(false);
        return;
      }
      if (data.check_result) setFeedback(data.check_result);
      if (data.status === 'success') {
        if (data.image_url) {
          setGeneratedImageUrl(data.image_url);
          setImageError(null);
          setIsTurnComplete(true);
        } else {
          setGeneratedImageUrl(null);
          setIsTurnComplete(false);
          setImageError(data?.error || 'Image failed to generate. Please try again.');
          if (data?.error) alert(data.error);
        }
      } else {
        setImageError(null);
      }
      // status === 'failed' 时已通过 setFeedback 显示 check_result，不进入下一轮
    } catch (e) { alert('Spell Failed') } finally { setIsProcessing(false) }
  };

  const handleNextRound = async () => {
    const sentenceToSave = (sentence.trim() || feedback?.corrected_sentence || '').trim();
    const allSentences = [...completedSentences, sentenceToSave];
    setCompletedSentences(allSentences);

    if (currentRound >= 5) {
      setShowFinalStory(true);
      setIsGeneratingStory(true);
      setSentence('');
      setFeedback(null);
      setGeneratedImageUrl(null);
      setIsTurnComplete(false);
      try {
        const res = await fetch(`${API_BASE}/api/generate_final_story`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            sentences: allSentences.slice(-5),
            scene: 'Dating',
            character,
            story_style: 'mature_romantic',
            story_mode: 'romance',
            protagonist_profile: PROTAGONIST_PROFILES[heroine],
            is_adult: ageGate === 'adult',
          }),
        });
        const data = await res.json();
        if (data.status === 'success') {
          setStoryResult({
            story_text: data.story_text || '',
            image_urls: data.image_urls || [],
            vocabulary: data.vocabulary || [],
            sentences: allSentences.slice(-5),
          });
        } else {
          setStoryResult({
            story_text: '',
            image_urls: [],
            vocabulary: [],
            sentences: [],
          });
          if (data?.error) alert(data.error);
        }
      } catch (e) {
        alert('Failed to generate story');
        setStoryResult(null);
      } finally {
        setIsGeneratingStory(false);
      }
      return;
    }

    setSentence('');
    setFeedback(null);
    setGeneratedImageUrl(null);
    setIsTurnComplete(false);
    fetchMagicWords(currentRound + 1, 3);
  };

  const handlePlayAgain = () => {
    setShowFinalStory(false);
    setStoryResult(null);
    setCompletedSentences([]);
    setCurrentRound(1);
    setRecentWords([]);
    fetchMagicWords(1, 3);
  };

  const sentenceForShare = () =>
    (sentence || feedback?.corrected_sentence || '').trim();

  /** 生成 1:1 心动海报并弹出展示层（长按保存 + 独立复制文案） */
  const handleGenerateHeartPoster = async () => {
    if (!generatedImageUrl) return;
    setIsShareSaving(true);
    setPosterDataUrl(null);
    try {
      const dataUrl = await exportPosterToDataUrl();
      if (dataUrl) {
        setPosterDataUrl(dataUrl);
        setShowPosterLayer(true);
      } else {
        const ok = await downloadCgExportCard(`WordWizard_round${currentRound}_poster.png`);
        if (!ok) handleDownload();
      }
    } catch (e) {
      console.error(e);
      handleDownload();
    } finally {
      setIsShareSaving(false);
    }
  };

  const handleCopyPostText = async () => {
    try {
      await navigator.clipboard.writeText(buildShareText(character, sentenceForShare()));
      setCopyPostHint('已复制到剪贴板');
      window.setTimeout(() => setCopyPostHint(null), 2200);
    } catch {
      setCopyPostHint('复制失败，请长按文案手动复制');
      window.setTimeout(() => setCopyPostHint(null), 2800);
    }
  };

  const handleDownloadPosterFile = () => {
    if (!posterDataUrl) return;
    const a = document.createElement('a');
    a.href = posterDataUrl;
    a.download = `WordWizard_round${currentRound}_poster.png`;
    a.click();
  };

  const handleDownload = () => {
    if (!generatedImageUrl) return;
    const sentenceText = sentence || feedback?.corrected_sentence || '';
    const img = new Image();
    img.crossOrigin = 'anonymous';
    img.src = generatedImageUrl;
    img.onload = () => {
      const size = 1024;
      const canvas = document.createElement('canvas');
      canvas.width = size;
      canvas.height = size;
      const ctx = canvas.getContext('2d');
      if (!ctx) return;

      // 绘制原图（居中裁剪为正方形）
      const iw = img.width;
      const ih = img.height;
      const scale = Math.max(size / iw, size / ih);
      const dw = iw * scale;
      const dh = ih * scale;
      const dx = (size - dw) / 2;
      const dy = (size - dh) / 2;
      ctx.drawImage(img, dx, dy, dw, dh);

      // 文字背景条
      const barHeight = 140;
      ctx.fillStyle = 'rgba(0,0,0,0.65)';
      ctx.fillRect(0, size - barHeight, size, barHeight);

      // 绘制句子
      ctx.font = '24px "Segoe UI", system-ui, -apple-system, BlinkMacSystemFont';
      ctx.fillStyle = '#ffffff';
      ctx.textBaseline = 'top';
      const padding = 32;
      const maxWidth = size - padding * 2;
      const text = sentenceText.trim() || 'Word Wizard';

      const words = text.split(' ');
      let line = '';
      let y = size - barHeight + padding / 2;
      for (const w of words) {
        const testLine = line ? line + ' ' + w : w;
        const metrics = ctx.measureText(testLine);
        if (metrics.width > maxWidth) {
          ctx.fillText(line, padding, y);
          line = w;
          y += 30;
        } else {
          line = testLine;
        }
      }
      if (line) ctx.fillText(line, padding, y);

      // 直接触发下载，避免被浏览器当作弹窗拦截
      const dataUrl = canvas.toDataURL('image/png');
      const link = document.createElement('a');
      link.href = dataUrl;
      link.download = `WordWizard_${currentRound}.png`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
    };
  };

  // Build segments for story text: string segments and phrase segments (for underlining)
  const storySegments = (() => {
    if (!storyResult?.story_text) return [storyResult?.story_text ?? ''];
    const vocab = [...(storyResult.vocabulary || [])].sort((a, b) => b.phrase.length - a.phrase.length);
    const segments: (string | { type: 'phrase'; phrase: string; explanation: string })[] = [];
    let remaining = storyResult.story_text;
    while (remaining.length > 0) {
      let best: { idx: number; len: number; v: { phrase: string; explanation: string } } | null = null;
      for (const v of vocab) {
        if (!v.phrase) continue;
        const i = remaining.indexOf(v.phrase);
        if (i !== -1 && (best === null || i < best.idx))
          best = { idx: i, len: v.phrase.length, v };
      }
      if (best === null) {
        segments.push(remaining);
        break;
      }
      if (best.idx > 0) segments.push(remaining.slice(0, best.idx));
      segments.push({ type: 'phrase', phrase: best.v.phrase, explanation: best.v.explanation });
      remaining = remaining.slice(best.idx + best.len);
    }
    return segments;
  })();

  const avatarButtonStyle = (selected: boolean) => ({
    width: '42px', height: '42px', borderRadius: '50%', padding: 0, overflow: 'hidden', cursor: 'pointer',
    border: selected ? `2px solid ${theme.pink}` : `2px solid transparent`,
    boxShadow: selected ? `0 0 12px ${theme.pink}` : 'none',
    transition: 'all 0.3s', opacity: selected ? 1 : 0.4, background: 'none'
  });

  if (showFinalStory) {
    return (
      <div style={{
        minHeight: '100vh', width: '100vw', backgroundColor: theme.bg,
        backgroundImage: 'radial-gradient(circle at center, #1a1a1a 0%, #050505 100%)',
        backgroundSize: 'cover', color: '#fff',
        fontFamily: '"Segoe UI", sans-serif', position: 'relative', paddingBottom: 48,
      }}>
        <header style={{ background: 'rgba(0,0,0,0.5)', backdropFilter: 'blur(15px)', padding: '12px 24px', borderBottom: `1px solid ${theme.pink}40`, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <h1 style={{ color: theme.pink, margin: 0, fontSize: '1.2rem', fontWeight: 800 }}>Your Story</h1>
          <button
            onClick={handlePlayAgain}
            style={{
              padding: '8px 20px', borderRadius: 999, border: `2px solid ${theme.pink}`, background: 'transparent',
              color: theme.pink, cursor: 'pointer', fontWeight: 700, fontSize: '0.9rem',
            }}
          >
            Play again
          </button>
        </header>
        {isGeneratingStory ? (
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', minHeight: '60vh', gap: 16 }}>
            <span className="heart-beat" style={{ fontSize: '3rem' }}>💖</span>
            <p style={{ color: theme.pinkLight, fontSize: '1.1rem' }}>Generating your story and images...</p>
          </div>
        ) : storyResult && (
          <div style={{ maxWidth: 720, margin: '0 auto', padding: 24 }}>
            <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 16 }}>
              <button
                onClick={async () => {
                  const el = storyContentRef.current
                  if (!el) return
                  try {
                    const canvas = await html2canvas(el, {
                      backgroundColor: '#0a0a0a',
                      scale: 2,
                      useCORS: true,
                      allowTaint: true,
                      logging: false,
                    })
                    const dataUrl = canvas.toDataURL('image/png')
                    const link = document.createElement('a')
                    link.href = dataUrl
                    link.download = 'WordWizard_Story.png'
                    link.click()
                  } catch (e) {
                    alert('Download failed')
                  }
                }}
                style={{
                  padding: '10px 24px', borderRadius: 999, border: 'none',
                  background: `linear-gradient(135deg, ${theme.pinkDark}, ${theme.pink})`,
                  color: '#fff', cursor: 'pointer', fontWeight: 700, fontSize: '0.9rem',
                }}
              >
                💾 保存整片图文
              </button>
            </div>
            <div
              ref={storyContentRef}
              style={{
                background: '#0a0a0a',
                padding: 28,
                borderRadius: 16,
                border: `1px solid ${theme.pink}40`,
              }}
            >
              <h2 style={{ color: theme.pink, marginTop: 0, marginBottom: 24, fontSize: '1.25rem', textAlign: 'center' }}>Your Story</h2>
              {/* 5 张配文的图：每张图下面对应一句情节 */}
              {[0, 1, 2, 3, 4].map((i) => (
                <div key={i} style={{ marginBottom: 28 }}>
                  <div style={{ width: '100%', maxWidth: 560, margin: '0 auto 10px', borderRadius: 12, overflow: 'hidden', boxShadow: '0 4px 20px rgba(0,0,0,0.5)' }}>
                    {storyResult.image_urls[i] ? (
                      <img
                        src={storyResult.image_urls[i]!}
                        alt={`Scene ${i + 1}`}
                        style={{ width: '100%', display: 'block', objectFit: 'cover' }}
                        crossOrigin="anonymous"
                      />
                    ) : (
                      <div style={{ width: '100%', aspectRatio: '1', background: 'rgba(255,255,255,0.06)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#666' }}>
                        Scene {i + 1} (no image)
                      </div>
                    )}
                  </div>
                  <p style={{ margin: 0, color: theme.pinkLight, fontSize: '0.95rem', lineHeight: 1.5, textAlign: 'center', fontStyle: 'italic' }}>
                    {storyResult.sentences[i] || `Beat ${i + 1}`}
                  </p>
                </div>
              ))}
              <div style={{
                background: 'rgba(255,255,255,0.06)', borderRadius: 12, padding: 20, marginBottom: 20,
                border: `1px solid ${theme.pink}30`, lineHeight: 1.7, fontSize: '1.05rem', color: '#e5e7eb',
              }}>
                <p style={{ margin: 0, whiteSpace: 'pre-wrap' }}>
                  {storySegments.map((seg, i) =>
                    typeof seg === 'string' ? (
                      seg
                    ) : (
                      <span
                        key={i}
                        title={seg.explanation}
                        style={{ textDecoration: 'underline', textDecorationColor: theme.pink, textUnderlineOffset: 3, cursor: 'help' }}
                      >
                        {seg.phrase}
                      </span>
                    )
                  )}
                </p>
              </div>
              {storyResult.vocabulary && storyResult.vocabulary.length > 0 && (
                <section style={{ background: 'rgba(255,255,255,0.06)', borderRadius: 12, padding: 16, border: `1px solid ${theme.pink}30` }}>
                  <h3 style={{ color: theme.pink, marginTop: 0, marginBottom: 10, fontSize: '0.95rem', letterSpacing: '0.05em' }}>📖 Glossary</h3>
                  <ul style={{ margin: 0, paddingLeft: 20, color: '#e5e7eb', fontSize: '0.9rem', lineHeight: 1.7 }}>
                    {storyResult.vocabulary.map((v, j) => (
                      <li key={j}><strong style={{ color: theme.pinkLight }}>{v.phrase}</strong> — {v.explanation}</li>
                    ))}
                  </ul>
                </section>
              )}
            </div>
          </div>
        )}
      </div>
    );
  }

  return (
    <div style={{
      height: '100vh', width: '100vw', backgroundColor: theme.bg,
      backgroundImage: generatedImageUrl ? `url(${generatedImageUrl})` : 'radial-gradient(circle at center, #1a1a1a 0%, #050505 100%)',
      backgroundSize: 'cover', backgroundPosition: 'center', color: '#fff',
      fontFamily: '"Segoe UI", sans-serif', position: 'relative', overflow: 'hidden'
    }}>
      {ageGate === 'unknown' && (
        <div style={{
          position: 'fixed',
          inset: 0,
          zIndex: 50,
          background: 'rgba(0,0,0,0.85)',
          backdropFilter: 'blur(20px)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}>
          <div style={{
            background: 'rgba(15,15,20,0.96)',
            borderRadius: 18,
            padding: '28px 36px',
            border: `1px solid ${theme.pink}`,
            boxShadow: `0 24px 60px rgba(0,0,0,0.9)`,
            maxWidth: 420,
            width: '90%',
            textAlign: 'center',
          }}>
            <div style={{ fontSize: '1.3rem', color: theme.pinkLight, fontWeight: 800, letterSpacing: '0.12em', marginBottom: 12 }}>
              WORD WIZARD
            </div>
            <div style={{ fontSize: '0.9rem', color: '#e5e7eb', marginBottom: 20 }}>
              Are you over 18 years old?
            </div>
            <div style={{ display: 'flex', justifyContent: 'center', gap: 12 }}>
              <button
                onClick={() => setAgeGate('minor')}
                style={{
                  padding: '8px 18px',
                  borderRadius: 999,
                  border: `1px solid ${theme.border}`,
                  background: 'transparent',
                  color: '#e5e7eb',
                  cursor: 'pointer',
                  fontWeight: 600,
                  fontSize: '0.85rem',
                }}
              >
                No, under 18
              </button>
              <button
                onClick={() => setAgeGate('adult')}
                style={{
                  padding: '8px 24px',
                  borderRadius: 999,
                  border: 'none',
                  background: `linear-gradient(135deg, ${theme.pinkDark}, ${theme.pink})`,
                  color: '#fff',
                  cursor: 'pointer',
                  fontWeight: 700,
                  fontSize: '0.9rem',
                  boxShadow: `0 0 20px ${theme.pink}80`,
                }}
              >
                Yes, I am 18+
              </button>
            </div>
          </div>
        </div>
      )}
      <div style={{ position: 'absolute', inset: 0, background: generatedImageUrl ? 'linear-gradient(to bottom, rgba(0,0,0,0) 30%, rgba(0,0,0,0.85) 100%)' : 'none', zIndex: 1, pointerEvents: 'none' }}></div>

      {showBgmHint && bgmEnabled && (
        <div
          style={{
            position: 'fixed',
            bottom: '24px',
            left: '50%',
            transform: 'translateX(-50%)',
            zIndex: 25,
            padding: '10px 20px',
            background: 'rgba(0,0,0,0.75)',
            backdropFilter: 'blur(12px)',
            border: `1px solid ${theme.pink}40`,
            borderRadius: '999px',
            color: theme.pinkLight,
            fontSize: '0.85rem',
            fontWeight: 600,
            letterSpacing: '0.5px',
            boxShadow: `0 4px 20px rgba(0,0,0,0.5)`,
          }}
        >
          🎵 点击页面任意处开始播放背景音乐
        </div>
      )}

      <header style={{ position: 'absolute', top: 0, left: 0, right: 0, zIndex: 10, background: 'rgba(0,0,0,0.4)', backdropFilter: 'blur(15px)', padding: '10px 40px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: `1px solid rgba(236,72,153,0.15)` }}>
        <div style={{ flex: 1 }}>
          <h1 style={{ color: theme.pink, margin: 0, fontSize: '1.2rem', textShadow: `0 0 10px ${theme.pink}`, fontWeight: 800 }}>Word Wizard</h1>
        </div>

        <div style={{ display: 'flex', gap: '30px', alignItems: 'center' }}>
          <button
            onClick={() => setBgmEnabled(v => !v)}
            style={{
              height: '32px',
              padding: '0 12px',
              borderRadius: '999px',
              border: `1px solid rgba(236,72,153,0.55)`,
              background: 'rgba(0,0,0,0.35)',
              color: theme.pinkLight,
              cursor: 'pointer',
              fontWeight: 700,
              fontSize: '0.75rem',
              letterSpacing: '0.5px',
            }}
            aria-pressed={bgmEnabled}
          >
            {bgmEnabled ? 'BGM ON' : 'BGM OFF'}
          </button>
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
            <span style={{ fontSize: '0.65rem', color: theme.pinkLight, marginBottom: '6px', letterSpacing: '1px', fontWeight: 600 }}>CHOOSE YOUR DATE</span>
            <div style={{ display: 'flex', gap: '12px' }}>
              {CHARACTER_OPTIONS_BY_STYLE[portraitStyle].map(opt => (
                <div key={opt.name} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '2px' }}>
                  <button onClick={() => setCharacter(opt.name)} style={avatarButtonStyle(character === opt.name)}>
                    <AvatarImg src={opt.avatar} alt={opt.name} fallback={opt.name.slice(0, 2)} />
                  </button>
                  <span style={{ fontSize: '0.6rem', color: character === opt.name ? theme.pinkLight : '#666' }}>{opt.name}</span>
                  {character === opt.name && CHARACTER_TAGS[opt.name]?.map(tag => <span key={tag} style={{ fontSize: '0.45rem', color: theme.pink }}>• {tag}</span>)}
                </div>
              ))}
            </div>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
            <span style={{ fontSize: '0.65rem', color: theme.pinkLight, marginBottom: '6px', letterSpacing: '1px', fontWeight: 600 }}>YOUR PERSONA</span>
            <div style={{ display: 'flex', gap: '12px' }}>
              {PROFILE_OPTIONS_BY_STYLE[portraitStyle].map(opt => (
                <div key={opt.name} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '2px' }}>
                  <button onClick={() => setHeroine(opt.name)} style={avatarButtonStyle(heroine === opt.name)}>
                    <AvatarImg src={opt.avatar} alt={opt.name} fallback={String(opt.name).slice(0, 2)} />
                  </button>
                  <span style={{ fontSize: '0.6rem', color: heroine === opt.name ? theme.pinkLight : '#666' }}>{opt.name}</span>
                  {heroine === opt.name && CHARACTER_TAGS[opt.name]?.map(tag => <span key={tag} style={{ fontSize: '0.45rem', color: theme.pink }}>• {tag}</span>)}
                </div>
              ))}
            </div>
          </div>
        </div>
      </header>

      <audio ref={audioRef} preload="auto" />

      <div style={{ position: 'absolute', bottom: '40px', left: '50%', transform: 'translateX(-50%)', width: '85%', maxWidth: '1000px', zIndex: 20, display: 'flex', flexDirection: 'column', gap: '15px' }}>
        <div style={{ background: 'rgba(10,10,12,0.8)', backdropFilter: 'blur(25px)', border: `1px solid rgba(236,72,153,0.3)`, boxShadow: `0 10px 40px rgba(0,0,0,0.8)`, borderRadius: '16px', padding: '24px', display: 'flex', flexDirection: 'column', gap: '15px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ color: theme.pinkLight, fontSize: '0.8rem', fontWeight: 800 }}>ROUND {currentRound} / 5</span>
            <div style={{ display: 'flex', gap: '10px' }}>{isLoadingWords ? <span style={{ color: theme.pink }}>🔮 Spell Loading...</span> : magicWords.map((w, i)=><span key={i} style={{color: '#fff', background: `linear-gradient(45deg, ${theme.pinkDark}, ${theme.pink})`, padding: '4px 16px', borderRadius: '20px', fontSize: '0.85rem', fontWeight: 'bold'}}>{w}</span>)}</div>
          </div>

          {isProcessing && (
            <div style={{
              display: 'flex', alignItems: 'center', gap: '10px', padding: '8px 12px',
              background: 'rgba(236,72,153,0.08)', borderRadius: '10px',
              borderLeft: `3px solid ${theme.pink}`
            }}>
              <span className="heart-beat" style={{ fontSize: '1.5rem', lineHeight: 1 }}>💖</span>
              <span style={{ color: theme.pink, fontSize: '0.9rem', fontWeight: 500, textShadow: `0 0 8px ${theme.pink}80` }}>
                Casting Love Spell into precious moment...
              </span>
            </div>
          )}

          {/* 🌟 升级后的反馈区域 */}
          {feedback && (
            <div style={{
              background: 'rgba(255, 255, 255, 0.05)',
              backdropFilter: 'blur(10px)',
              borderLeft: `4px solid ${feedback.is_correct ? theme.pink : '#ef4444'}`,
              padding: '12px 20px',
              borderRadius: '12px',
              boxShadow: feedback.is_correct ? `0 0 20px ${theme.pink}30` : 'none'
            }}>
              <div style={{
                color: feedback.is_correct ? theme.pinkLight : '#f87171',
                fontWeight: 'bold',
                fontSize: '0.9rem',
                letterSpacing: '1px',
                display: 'flex',
                alignItems: 'center',
                gap: '8px'
              }}>
                {feedback.is_correct ? '✨ EXCELLENT JOB!' : '❌ INCANTATION FAILED'}
              </div>
              <div style={{
                fontSize: '0.95rem',
                color: '#fff',
                marginTop: '6px',
                lineHeight: '1.4',
                fontWeight: 400
              }}>
                {feedback.feedback}
              </div>
              {!feedback.is_correct && feedback.corrected_sentence && (
                <div style={{ color: theme.pinkLight, marginTop: '5px', fontSize: '0.85rem', opacity: 0.8 }}>
                  💡 Try: {feedback.corrected_sentence}
                </div>
              )}
            </div>
          )}

          {imageError && (
            <div style={{
              background: 'rgba(239, 68, 68, 0.12)',
              borderLeft: '4px solid #ef4444',
              padding: '10px 16px',
              borderRadius: '12px',
              color: '#fca5a5',
              fontSize: '0.9rem',
            }}>
              🖼️ {(() => {
                const m = imageError.toLowerCase();
                if (m.includes('failed to fetch') || m.includes('load failed')) {
                  return import.meta.env.DEV
                    ? '连不上后端：请另开终端在 backend 运行 ./run_dev.sh（或 uvicorn 指定 8002），再重启前端 npm run dev。'
                    : `连不上 API（${API_BASE || '未配置 VITE_API_BASE'}）。`;
                }
                if (m.includes('connection') || m.includes('network')) {
                  return '后端连不上 OpenRouter / 代理未通。请：① 代理软件已开；② backend/.env 里 OPENROUTER_PROXY=http://127.0.0.1:8001（HTTP 端口）；③ 保存后重启后端；④ 终端应出现「已配置代理」。';
                }
                if (m.includes('timeout') || m.includes('timed out')) return '图片生成超时，请稍后重试或换一句试试。';
                if (m.includes('request failed')) return '请求失败，请稍后重试或换一句试试。';
                if (m.includes('rate limit') || m.includes('rate-limited')) return '生成服务暂时繁忙，请稍后再试。';
                return imageError.includes('请') ? imageError : `${imageError} 请稍后重试或换一句试试。`;
              })()}
              <div style={{ marginTop: 8, fontSize: '0.72rem', opacity: 0.75, wordBreak: 'break-all' }}>{imageError}</div>
            </div>
          )}

          <div style={{ display: 'flex', gap: '20px', alignItems: 'flex-end' }}>
            <textarea value={sentence} onChange={(e)=>setSentence(e.target.value)} disabled={isProcessing||isTurnComplete} placeholder="Cast your spell with the words above..." style={{flex:1, height: '35px', background:'transparent', border:'none', borderBottom:`2px solid rgba(255,255,255,0.2)`, color:'#fff', fontSize:'1.1rem', outline:'none', resize:'none'}}/>
            {!isTurnComplete ? (
              <button onClick={handleSubmitSentence} disabled={!sentence.trim()||isProcessing} style={{padding:'0 25px', height: '40px', background: !sentence.trim()||isProcessing ? theme.border : `linear-gradient(135deg, ${theme.pinkDark}, ${theme.pink})`, color:'#fff', border:'none', borderRadius: '20px', cursor: 'pointer', fontWeight:'bold'}}>{isProcessing?'⏳ RENDERING...':'CONFIRM'}</button>
            ) : (
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '10px', alignItems: 'center', justifyContent: 'flex-end' }}>
                <button
                  type="button"
                  onClick={handleGenerateHeartPoster}
                  disabled={isShareSaving}
                  style={{
                    padding: '0 18px',
                    height: '42px',
                    background: isShareSaving ? theme.border : `linear-gradient(135deg, ${theme.pinkDark}, ${theme.pink})`,
                    border: 'none',
                    color: '#fff',
                    borderRadius: '21px',
                    cursor: isShareSaving ? 'wait' : 'pointer',
                    fontWeight: 800,
                    fontSize: '0.8rem',
                    letterSpacing: '0.03em',
                    boxShadow: `0 4px 20px ${theme.pink}55`,
                  }}
                >
                  {isShareSaving ? '生成中…' : '🎁 生成专属心动海报'}
                </button>
                <button
                  type="button"
                  onClick={handleDownload}
                  style={{
                    padding: '0 14px',
                    height: '40px',
                    background: 'transparent',
                    border: `1px solid ${theme.pink}66`,
                    color: theme.pinkLight,
                    borderRadius: '20px',
                    cursor: 'pointer',
                    fontWeight: 600,
                    fontSize: '0.75rem',
                  }}
                >
                  仅保存图片
                </button>
                <button onClick={handleNextRound} style={{padding:'0 20px', height: '40px', background:'transparent', border:`2px solid ${theme.pink}`, color:theme.pink, borderRadius:'20px', cursor:'pointer', fontWeight:'bold'}}>NEXT ➔</button>
              </div>
            )}
          </div>
        </div>
      </div>
      {isTurnComplete && generatedImageUrl ? (
        <CgExportPortal
          imageUrl={generatedImageUrl}
          sentence={sentence || feedback?.corrected_sentence || ''}
          character={character}
        />
      ) : null}

      {/* 心动海报展示层：长按保存 + 复制发帖文案 */}
      {showPosterLayer && posterDataUrl && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="心动海报"
          style={{
            position: 'fixed',
            inset: 0,
            zIndex: 9999,
            background: 'rgba(0,0,0,0.92)',
            backdropFilter: 'blur(12px)',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '16px 20px 28px',
            gap: 16,
          }}
          onClick={() => setShowPosterLayer(false)}
          onKeyDown={(e) => e.key === 'Escape' && setShowPosterLayer(false)}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              position: 'relative',
              width: 'min(88vw, 400px)',
              maxHeight: 'min(88vw, 400px)',
              aspectRatio: '1',
            }}
          >
            <img
              src={posterDataUrl}
              alt="专属心动海报，可长按保存"
              draggable={false}
              style={{
                width: '100%',
                height: '100%',
                objectFit: 'contain',
                borderRadius: 14,
                border: `3px solid ${theme.pink}`,
                boxShadow: `0 0 36px ${theme.pink}44`,
                display: 'block',
                background: '#000',
              }}
            />
            <div
              className="poster-longpress-hint"
              style={{
                position: 'absolute',
                left: 0,
                right: 0,
                bottom: '14%',
                textAlign: 'center',
                pointerEvents: 'none',
                color: '#fff',
                fontSize: '0.95rem',
                fontWeight: 700,
                letterSpacing: '0.06em',
                padding: '0 12px',
              }}
            >
              👇 长按图片保存到手机
            </div>
          </div>

          <div
            onClick={(e) => e.stopPropagation()}
            style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 10, width: '100%', maxWidth: 400 }}
          >
            <button
              type="button"
              onClick={handleCopyPostText}
              style={{
                width: '100%',
                padding: '14px 20px',
                borderRadius: 14,
                border: `1px solid ${theme.pink}88`,
                background: 'rgba(236,72,153,0.15)',
                color: theme.pinkLight,
                fontWeight: 800,
                fontSize: '0.9rem',
                cursor: 'pointer',
                letterSpacing: '0.08em',
              }}
            >
              📋 一键复制发帖文案
            </button>
            {copyPostHint && (
              <span style={{ fontSize: '0.8rem', color: theme.pinkLight }}>{copyPostHint}</span>
            )}
            <button
              type="button"
              onClick={handleDownloadPosterFile}
              style={{
                width: '100%',
                padding: '10px',
                borderRadius: 12,
                border: '1px solid rgba(255,255,255,0.15)',
                background: 'transparent',
                color: '#9ca3af',
                fontSize: '0.78rem',
                cursor: 'pointer',
              }}
            >
              💾 电脑端：点击下载海报文件
            </button>
            <button
              type="button"
              onClick={() => setShowPosterLayer(false)}
              style={{
                marginTop: 4,
                padding: '8px 24px',
                background: 'transparent',
                border: 'none',
                color: '#6b7280',
                fontSize: '0.8rem',
                cursor: 'pointer',
              }}
            >
              关闭
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
