import { ImageResponse } from 'next/og';

export const alt = 'Open Learn — an AI study partner for curious minds';
export const size = { width: 1200, height: 630 };
export const contentType = 'image/png';

export default function OpenGraphImage() {
  return new ImageResponse(
    <div style={{ display: 'flex', width: '100%', height: '100%', padding: '76px', flexDirection: 'column', justifyContent: 'space-between', background: 'radial-gradient(ellipse at 50% 10%, #263629 0%, #151a16 45%, #101311 100%)', color: '#eff3ed', fontFamily: 'Arial, sans-serif' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '14px', color: '#dcebd5', fontSize: 24, fontWeight: 600 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', width: 45, height: 45, borderRadius: 14, background: '#dcebd5', color: '#28372a', fontSize: 20 }}>OL</div>
        Open Learn
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', maxWidth: 930 }}>
        <div style={{ marginBottom: 24, color: '#b8c9b0', fontSize: 17, fontWeight: 600, letterSpacing: 4 }}>A SPACE FOR YOUR CURIOSITY</div>
        <div style={{ fontSize: 76, fontWeight: 500, letterSpacing: -4, lineHeight: 1.06 }}>There’s a world behind every question.</div>
        <div style={{ maxWidth: 830, marginTop: 26, color: '#b7c2b4', fontSize: 25, lineHeight: 1.45 }}>An AI study partner that helps you understand, save what clicks, and come back to it.</div>
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', color: '#a8b4a5', fontSize: 18 }}>
        <span>Thoughtful conversations · Notes · Review</span>
        <span>Open Learn · A space for your curiosity</span>
      </div>
    </div>,
    { ...size },
  );
}
