import { createPortal } from 'react-dom'
import html2canvas from 'html2canvas'

const PINK = '#ec4899'
const PINK_LIGHT = '#fbcfe8'

export function buildShareText(character: string, sentence: string): string {
  const s = sentence.trim() || '（我的造句）'
  return (
    `我的英语造句居然变成了电影画面！和 ${character} 的羁绊加深了💕\n\n我的造句：「${s}」\n\n（海报图底部已自带安利文案，可直接发图）\n快来 Word Wizard 测测你的专属心动 CG 吧！`
  )
}

/** 导出图固定 1:1，与分享参考海报比例一致 */
const EXPORT_SIZE = 720

/**
 * 分享导出卡：1:1 方形 CG + 底部半透明字幕条（文案叠在图上，非独立黑块）
 */
export function CgExportPortal({
  imageUrl,
  sentence,
  character,
}: {
  imageUrl: string
  sentence: string
  character: string
}) {
  if (!imageUrl) return null
  const text = sentence.trim() || 'Word Wizard'
  return createPortal(
    <div
      id="cg-export-container"
      style={{
        position: 'fixed',
        left: -12000,
        top: 0,
        width: EXPORT_SIZE,
        height: EXPORT_SIZE,
        boxSizing: 'border-box',
        borderRadius: 12,
        overflow: 'hidden',
        background: '#000',
        border: `3px solid ${PINK}`,
        boxShadow: `0 0 30px ${PINK}55`,
      }}
    >
      <div
        style={{
          position: 'absolute',
          inset: 0,
          width: '100%',
          height: '100%',
        }}
      >
        <img
          src={imageUrl}
          alt=""
          crossOrigin="anonymous"
          style={{
            width: '100%',
            height: '100%',
            objectFit: 'cover',
            objectPosition: 'center center',
            display: 'block',
          }}
        />
        <div
          style={{
            position: 'absolute',
            top: 14,
            left: '50%',
            transform: 'translateX(-50%)',
            background: 'rgba(236,72,153,0.9)',
            color: '#fff',
            padding: '6px 22px',
            borderRadius: 999,
            fontSize: 10,
            fontWeight: 800,
            letterSpacing: '0.18em',
            border: `1px solid ${PINK_LIGHT}77`,
            whiteSpace: 'nowrap',
            zIndex: 2,
          }}
        >
          EXCELLENT JOB
        </div>

        {/* 底部电影字幕条：半透明叠在图上（参考 1:1 海报） */}
        <div
          style={{
            position: 'absolute',
            left: 0,
            right: 0,
            bottom: 0,
            zIndex: 1,
            background: 'linear-gradient(180deg, transparent 0%, rgba(0,0,0,0.55) 28%, rgba(0,0,0,0.82) 100%)',
            padding: '56px 22px 22px',
            boxSizing: 'border-box',
          }}
        >
          <p
            style={{
              margin: '0 0 12px',
              color: '#fff',
              textAlign: 'left',
              fontSize: 15,
              fontWeight: 500,
              fontFamily:
                '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, "PingFang SC", "Microsoft YaHei", sans-serif',
              lineHeight: 1.45,
              wordBreak: 'break-word',
              textTransform: 'lowercase',
              textShadow: '0 1px 8px rgba(0,0,0,0.9)',
            }}
          >
            &quot;{text}&quot;
          </p>
          <p
            style={{
              margin: 0,
              fontSize: 11,
              lineHeight: 1.55,
              color: 'rgba(209,213,219,0.95)',
              textAlign: 'left',
              fontFamily:
                '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Microsoft YaHei", sans-serif',
              textShadow: '0 1px 6px rgba(0,0,0,0.85)',
            }}
          >
            我的英语造句变成了电影画面！和{' '}
            <span style={{ color: PINK_LIGHT, fontWeight: 700 }}>{character}</span> 的羁绊加深了💕 ·{' '}
            <span style={{ color: PINK, fontWeight: 800 }}>Word Wizard</span>
          </p>
        </div>
      </div>
    </div>,
    document.body
  )
}

async function captureCgExportCanvas(): Promise<HTMLCanvasElement | null> {
  const el = document.getElementById('cg-export-container')
  if (!el) return null
  try {
    await new Promise((r) => setTimeout(r, 500))
    return await html2canvas(el as HTMLElement, {
      useCORS: true,
      allowTaint: false,
      scale: 2,
      backgroundColor: '#000000',
      logging: false,
      width: EXPORT_SIZE,
      height: EXPORT_SIZE,
      windowWidth: EXPORT_SIZE,
    })
  } catch {
    return null
  }
}

/** 生成 1:1 海报 data URL，用于弹层展示（手机可长按保存） */
export async function exportPosterToDataUrl(): Promise<string | null> {
  const canvas = await captureCgExportCanvas()
  return canvas ? canvas.toDataURL('image/png') : null
}

export async function downloadCgExportCard(filename: string): Promise<boolean> {
  try {
    const canvas = await captureCgExportCanvas()
    if (!canvas) return false
    const blob = await new Promise<Blob | null>((res) => canvas.toBlob((b) => res(b), 'image/png'))
    if (!blob) return false
    const a = document.createElement('a')
    const url = URL.createObjectURL(blob)
    a.href = url
    a.download = filename
    a.click()
    URL.revokeObjectURL(url)
    return true
  } catch {
    return false
  }
}

export function ShareSuccessModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  if (!open) return null
  return createPortal(
    <div
      role="dialog"
      aria-modal="true"
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 10000,
        background: 'rgba(0,0,0,0.82)',
        backdropFilter: 'blur(10px)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 20,
      }}
      onClick={onClose}
      onKeyDown={(e) => e.key === 'Escape' && onClose()}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: '#111827',
          border: `1px solid ${PINK}`,
          borderRadius: 16,
          padding: '36px 28px',
          maxWidth: 380,
          width: '100%',
          textAlign: 'center',
          boxShadow: `0 0 48px ${PINK}44`,
        }}
      >
        <div style={{ fontSize: 52, marginBottom: 14 }}>✨</div>
        <h3 style={{ color: PINK, fontSize: 24, fontWeight: 800, margin: '0 0 12px', letterSpacing: '0.06em' }}>
          保存成功！
        </h3>
        <p style={{ color: '#d1d5db', fontSize: 15, lineHeight: 1.75, margin: '0 0 16px' }}>
          绝美 CG 已存入你的相册
          <br />
          <span style={{ color: PINK_LIGHT, fontWeight: 700 }}>
            海报最下方已自带安利文案
          </span>
          — 直接发小红书 / 朋友圈，传播门槛超低！
        </p>
        <p style={{ fontSize: 12, color: '#6b7280', margin: '0 0 24px', lineHeight: 1.55 }}>
          剪贴板里也备了一份完整文案，需要长文安利时可粘贴使用。
        </p>
        <button
          type="button"
          onClick={onClose}
          style={{
            width: '100%',
            padding: '14px 20px',
            border: 'none',
            borderRadius: 999,
            fontWeight: 800,
            letterSpacing: '0.12em',
            cursor: 'pointer',
            color: '#fff',
            background: `linear-gradient(90deg, ${PINK}, #a855f7)`,
            boxShadow: `0 0 20px ${PINK}55`,
          }}
        >
          GOT IT
        </button>
      </div>
    </div>,
    document.body
  )
}
