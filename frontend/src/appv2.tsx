import { useState, useEffect } from 'react'

interface AiFeedback {
  is_correct: boolean;
  feedback: string;
  corrected_sentence: string | null;
}
const PROTAGONIST_PROFILES = {
  "Fresh Chic": "Cinematic portrait of a young woman, cute short bob hair, wearing a cozy warm oversized sweater, soft smooth flawless skin. Cinematic lighting, soft glow bloom, photorealistic movie still.",
  "Night Elegance": "Cinematic portrait of a young woman, long straight black hair, wearing an elegant silk evening gown, soft smooth flawless skin. Cinematic lighting, soft glow bloom, photorealistic movie still.",
  "Executive Aura": "Cinematic portrait of a young woman, sharp confident eyes, wearing a tailored black blazer, confident office style, soft smooth flawless skin. Cinematic lighting, photorealistic movie still.",
  "Grace Classic": "Cinematic portrait of a young woman, auburn hair tied in an elegant updo, wearing a classic chic vintage dress, soft smooth flawless skin. Cinematic warm lighting, photorealistic movie still."
} as const

const MALE_LEADS = ['Adrien', 'Richard', 'Damon', 'Lucas'] as const
type PortraitStyle = 'cinematic' | 'comic'

const CHARACTER_OPTIONS_BY_STYLE: Record<PortraitStyle, Array<{ name: typeof MALE_LEADS[number]; avatar: string }>> = {
  cinematic: [
    { name: 'Adrien', avatar: '/split_faces/cinematic_male_adrien_top.png' },
    { name: 'Richard', avatar: '/split_faces/cinematic_male_richard_top.png' },
    { name: 'Damon', avatar: '/split_faces/cinematic_male_damon_bottom.png' },
    { name: 'Lucas', avatar: '/split_faces/cinematic_male_lucas_bottom.png' }
  ],
  comic: [
    { name: 'Adrien', avatar: '/split_faces/comic_male_adrien_top.png' },
    { name: 'Richard', avatar: '/split_faces/comic_male_richard_top.png' },
    { name: 'Damon', avatar: '/split_faces/comic_male_damon_bottom.png' },
    { name: 'Lucas', avatar: '/split_faces/comic_male_lucas_bottom.png' }
  ]
}

const PROFILE_OPTIONS_BY_STYLE: Record<PortraitStyle, Array<{ name: keyof typeof PROTAGONIST_PROFILES; avatar: string }>> = {
  cinematic: [
    { name: 'Fresh Chic', avatar: '/split_faces/cinematic_female_fresh_chic.png' },
    { name: 'Night Elegance', avatar: '/split_faces/cinematic_female_night_elegance.png' },
    { name: 'Executive Aura', avatar: '/split_faces/cinematic_female_executive_aura.png' },
    { name: 'Grace Classic', avatar: '/split_faces/cinematic_female_grace_classic.png' }
  ],
  comic: [
    { name: 'Fresh Chic', avatar: '/split_faces/comic_female_fresh_chic.png' },
    { name: 'Night Elegance', avatar: '/split_faces/comic_female_night_elegance.png' },
    { name: 'Executive Aura', avatar: '/split_faces/comic_female_executive_aura.png' },
    { name: 'Grace Classic', avatar: '/split_faces/comic_female_grace_classic.png' }
  ]
}

const theme = { bg: '#050505', pink: '#ec4899', pinkDark: '#be185d', pinkLight: '#fbcfe8', border: '#374151' }

export default function App() {
  const [scene] = useState('Dating')
  const [character, setCharacter] = useState('Adrien')
  const [heroine, setHeroine] = useState<keyof typeof PROTAGONIST_PROFILES>('Night Elegance')
  const [portraitStyle, setPortraitStyle] = useState<PortraitStyle>('cinematic')
  const [wordCount] = useState(3)
  const [storyStyle, setStoryStyle] = useState('mature_romantic')

  const [currentRound, setCurrentRound] = useState(1)
  const [magicWords, setMagicWords] = useState<string[]>([])
  const [sentence, setSentence] = useState('')
  const [feedback, setFeedback] = useState<AiFeedback | null>(null)
  const [generatedImageUrl, setGeneratedImageUrl] = useState<string | null>(null)

  const [isLoadingWords, setIsLoadingWords] = useState(true)
  const [isProcessing, setIsProcessing] = useState(false)
  const [isTurnComplete, setIsTurnComplete] = useState(false)

  useEffect(() => { fetchMagicWords(1, 3) }, [])

  const fetchMagicWords = async (roundToSet = currentRound, countToFetch = wordCount) => {
    setIsLoadingWords(true); setSentence(''); setFeedback(null); setGeneratedImageUrl(null); setIsTurnComplete(false);
    try {
      const response = await fetch('http://localhost:8000/api/get_words', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scene, character, word_count: countToFetch, story_style: storyStyle })
      })
      const data = await response.json()
      setMagicWords(data.words); setCurrentRound(roundToSet);
    } catch (e) { alert('后端未连接') } finally { setIsLoadingWords(false) }
  }

  const handleSubmitSentence = async () => {
    if (isProcessing) return;
    setIsProcessing(true); setFeedback(null);
    try {
      const payload = { sentence, required_words: magicWords, scene, character, protagonist_profile: PROTAGONIST_PROFILES[heroine], portrait_style: portraitStyle, story_style: storyStyle }
      const response = await fetch('http://localhost:8000/api/process_turn', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload)
      })
      const data = await response.json()
      if (data.status === 'success') {
        setFeedback(data.check_result)
        if (data.image_url) setGeneratedImageUrl(data.image_url)
        setIsTurnComplete(true)
      }
    } catch (e) { alert('生图失败') } finally { setIsProcessing(false) }
  }

  const handleDownload = () => {
    if (!generatedImageUrl) return;
    const link = document.createElement('a');
    link.href = generatedImageUrl;
    link.download = `WordWizard_CG_Round${currentRound}.png`;
    link.click();
  };

  const avatarButtonStyle = (selected: boolean) => ({
    width: '42px', height: '42px', borderRadius: '50%', padding: 0, overflow: 'hidden', cursor: 'pointer',
    border: selected ? `2px solid ${theme.pink}` : `2px solid transparent`,
    boxShadow: selected ? `0 0 12px ${theme.pink}` : 'none',
    transition: 'all 0.3s', opacity: selected ? 1 : 0.5, background: 'none'
  })

  return (
    <div style={{
      height: '100vh', width: '100vw', backgroundColor: theme.bg,
      backgroundImage: generatedImageUrl ? `url(${generatedImageUrl})` : 'radial-gradient(circle at center, #1a1a1a 0%, #050505 100%)',
      backgroundSize: 'cover', backgroundPosition: 'center', color: '#fff',
      fontFamily: '"Microsoft YaHei", sans-serif', position: 'relative', overflow: 'hidden'
    }}>
      <div style={{ position: 'absolute', inset: 0, background: generatedImageUrl ? 'linear-gradient(to bottom, rgba(0,0,0,0) 30%, rgba(0,0,0,0.85) 100%)' : 'none', zIndex: 1, pointerEvents: 'none' }}></div>

      {/* ========== 顶部控制台 (带 16 个人脸选项) ========== */}
      <header style={{ 
        position: 'absolute', top: 0, left: 0, right: 0, zIndex: 10, 
        background: 'rgba(0,0,0,0.4)', backdropFilter: 'blur(15px)', 
        padding: '10px 40px', display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        borderBottom: `1px solid rgba(236,72,153,0.15)`
      }}>
        <div style={{ flex: 1 }}>
          <h1 style={{ color: theme.pink, margin: 0, fontSize: '1.2rem', textShadow: `0 0 10px ${theme.pink}` }}>Word Wizard</h1>
          <div style={{ display: 'flex', gap: '10px', marginTop: '4px' }}>
            <select value={portraitStyle} onChange={(e)=>setPortraitStyle(e.target.value as PortraitStyle)} style={{background:'rgba(0,0,0,0.5)', color:theme.pinkLight, border:`1px solid ${theme.pink}`, borderRadius:'4px', fontSize:'0.75rem', cursor:'pointer'}}><option value="cinematic">电影质感</option><option value="comic">美式漫画</option></select>
            <select value={storyStyle} onChange={(e)=>setStoryStyle(e.target.value)} style={{background:'rgba(0,0,0,0.5)', color:theme.pinkLight, border:`1px solid ${theme.pink}`, borderRadius:'4px', fontSize:'0.75rem', cursor:'pointer'}}><option value="mature_romantic">成熟浪漫</option><option value="young_cute">年轻可爱</option></select>
          </div>
        </div>

        {/* 角色直选区 */}
        <div style={{ display: 'flex', gap: '30px', alignItems: 'center' }}>
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
            <span style={{ fontSize: '0.65rem', color: theme.pinkLight, marginBottom: '4px', textTransform: 'uppercase', letterSpacing: '1px', fontWeight: 600 }}>CHOOSE YOUR DATE</span>
            <div style={{ display: 'flex', gap: '6px' }}>
              {CHARACTER_OPTIONS_BY_STYLE[portraitStyle].map(opt => (
                <button key={opt.name} onClick={() => setCharacter(opt.name)} style={avatarButtonStyle(character === opt.name)}>
                  <img src={opt.avatar} alt={opt.name} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                </button>
              ))}
            </div>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
            <span style={{ fontSize: '0.65rem', color: theme.pinkLight, marginBottom: '4px', textTransform: 'uppercase', letterSpacing: '1px', fontWeight: 600 }}>YOUR PERSONA</span>
            <div style={{ display: 'flex', gap: '6px' }}>
              {PROFILE_OPTIONS_BY_STYLE[portraitStyle].map(opt => (
                <button key={opt.name} onClick={() => setHeroine(opt.name)} style={avatarButtonStyle(heroine === opt.name)}>
                  <img src={opt.avatar} alt={opt.name} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                </button>
              ))}
            </div>
          </div>
        </div>
      </header>

      {/* 底部悬浮对话框 */}
      <div style={{ position: 'absolute', bottom: '40px', left: '50%', transform: 'translateX(-50%)', width: '85%', maxWidth: '1000px', zIndex: 20, display: 'flex', flexDirection: 'column', gap: '15px' }}>
        {feedback && (
          <div style={{
            alignSelf: 'flex-start',
            background: 'rgba(255,255,255,0.05)',
            backdropFilter: 'blur(10px)',
            borderLeft: `4px solid ${feedback.is_correct ? theme.pink : '#ef4444'}`,
            padding: '12px 20px',
            borderRadius: '12px',
            boxShadow: feedback.is_correct ? `0 0 20px ${theme.pink}40, 0 4px 20px rgba(236,72,153,0.2)` : '0 4px 15px rgba(0,0,0,0.5)'
          }}>
            <div style={{
              color: feedback.is_correct ? theme.pinkLight : '#f87171',
              fontWeight: 'bold',
              fontSize: '0.95rem',
              letterSpacing: '1px',
              marginBottom: '6px',
              textShadow: feedback.is_correct ? `0 0 12px ${theme.pink}80` : 'none'
            }}>
              {feedback.is_correct ? '✨ EXCELLENT JOB!' : '❌ INCANTATION FAILED'}
            </div>
            <div style={{ fontSize: '0.95rem', color: '#fff', lineHeight: 1.5 }}>{feedback.feedback}</div>
            {!feedback.is_correct && feedback.corrected_sentence && (
              <div style={{
                marginTop: '10px',
                paddingTop: '10px',
                borderTop: '1px solid rgba(255,255,255,0.15)',
                color: theme.pinkLight,
                fontSize: '0.9rem',
                opacity: 0.95
              }}>
                <span style={{ fontWeight: 600 }}>💡 Advanced Casting 建议句型：</span> {feedback.corrected_sentence}
              </div>
            )}
          </div>
        )}

        <div style={{ background: 'rgba(10,10,12,0.8)', backdropFilter: 'blur(20px)', border: `1px solid rgba(236,72,153,0.3)`, boxShadow: `0 10px 40px rgba(0,0,0,0.8)`, borderRadius: '16px', padding: '24px', display: 'flex', flexDirection: 'column', gap: '20px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ color: theme.pinkLight, fontSize: '0.8rem', fontWeight: 'bold' }}>ROUND {currentRound} / 5</span>
            <div style={{ display: 'flex', gap: '10px' }}>
              {isLoadingWords ? <span style={{ color: theme.pink }}>🔮 命运抽取中...</span> : magicWords.map((w, i)=><span key={i} style={{color: '#fff', background: `linear-gradient(45deg, ${theme.pinkDark}, ${theme.pink})`, padding: '4px 14px', borderRadius: '20px', fontSize: '0.9rem', fontWeight: 'bold', boxShadow: `0 0 10px ${theme.pink}50`}}>{w}</span>)}
            </div>
          </div>

          <div style={{ display: 'flex', gap: '20px', alignItems: 'flex-end' }}>
            <textarea value={sentence} onChange={(e)=>setSentence(e.target.value)} disabled={isProcessing||isTurnComplete} placeholder="写下你们之间的对白..." style={{flex:1, height: '40px', background:'transparent', border:'none', borderBottom:`2px solid rgba(255,255,255,0.2)`, color:'#fff', fontSize:'1.2rem', outline:'none', resize:'none', transition: 'border-color 0.3s'}} onFocus={(e)=>e.target.style.borderBottom=`2px solid ${theme.pink}`}/>
            
            {!isTurnComplete ? (
              <button onClick={handleSubmitSentence} disabled={!sentence.trim()||isProcessing} style={{padding:'0 30px', height: '45px', background: !sentence.trim()||isProcessing ? theme.border : `linear-gradient(135deg, ${theme.pinkDark}, ${theme.pink})`, color:'#fff', border:'none', borderRadius: '24px', cursor: (!sentence.trim()||isProcessing)?'not-allowed':'pointer', fontWeight:'bold', fontSize:'1.1rem', boxShadow: sentence.trim()&&!isProcessing?`0 0 20px ${theme.pink}60`:'none'}}>{isProcessing?'⏳ 渲染中...':'确认 ✦'}</button>
            ) : (
              <div style={{ display: 'flex', gap: '12px' }}>
                <button onClick={handleDownload} style={{padding:'0 24px', height: '45px', background:'transparent', border:`1px solid ${theme.pink}`, color: theme.pink, borderRadius:'24px', cursor:'pointer', fontWeight:'bold', fontSize:'1rem'}}>💾 SAVE CG</button>
                <button onClick={()=>fetchMagicWords(currentRound+1, 3)} style={{padding:'0 30px', height: '45px', background:'transparent', border:`2px solid ${theme.pink}`, color: theme.pink, borderRadius:'24px', cursor:'pointer', fontWeight:'bold', fontSize:'1.1rem'}}>下一幕 ➔</button>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}