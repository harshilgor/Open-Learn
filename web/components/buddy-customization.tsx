"use client";
import {Buddy as Character, concepts, accessoryChoices} from './buddy-character';
import {defaultAppearance, type BuddyInput} from '@/lib/buddies';
import {useBuddyPresence} from '@/lib/buddy-presence';
import {useState} from 'react';

export const buddyColors={sage:'#B8CFA8',amber:'#F0BA68',blue:'#A9BDE2',rose:'#E99381',violet:'#BEA9DD'};

export function BuddyCustomization({value,onChange}:{value:BuddyInput;onChange:(value:BuddyInput)=>void}) {
  const look={...defaultAppearance,...value.appearance};
  const [reaction,setReaction]=useState(false);
  const presence=useBuddyPresence('customization-preview',look.sleepy);
  const appearance=(patch:Partial<typeof look>)=>onChange({...value,appearance:{...look,...patch}});
  return <div className="buddy-customization">
    <button type="button" className="buddy-preview" aria-label="Preview celebration" onClick={()=>setReaction(current=>!current)}>
      <Character index={look.shape} color={buddyColors[value.color]} {...look} expression={reaction?'Happy':presence} animated size={130}/>
      <small>{reaction?'Click to settle down':'Click to celebrate'}</small>
    </button>
    <label>Look<select value={look.shape} onChange={event=>appearance({shape:Number(event.target.value)})}>{concepts.map((shape,index)=><option key={shape.name} value={index}>{shape.name}</option>)}</select></label>
    <div className="buddy-swatches" aria-label="Body color">{Object.entries(buddyColors).map(([key,color])=><button type="button" key={key} aria-label={key} aria-pressed={key===value.color} style={{background:color}} onClick={()=>onChange({...value,color:key as BuddyInput['color']})}/>)}</div>
    <label>What should I help you with? <small>Optional</small><input maxLength={160} placeholder="e.g. Practicing physics and building intuition" value={value.focus||''} onChange={event=>onChange({...value,focus:event.target.value})}/></label>
    <details><summary>Outfit & little details</summary>
      <div className="buddy-accessories">{accessoryChoices.map(item=><button type="button" key={item} aria-pressed={look.accessories.includes(item)} onClick={()=>appearance({accessories:look.accessories.includes(item)?look.accessories.filter(x=>x!==item):[...look.accessories.filter(x=>!(['Beanie','Cap'].includes(item)&&['Beanie','Cap'].includes(x))),item]})}>{item}</button>)}</div>
      <label>Outfit palette<select value={look.palette} onChange={event=>appearance({palette:event.target.value as typeof look.palette})}><option value="original">Warm & cozy</option><option value="ocean">Ocean</option><option value="berry">Berry</option></select></label>
      <label>Eyes<select value={look.face} onChange={event=>appearance({face:event.target.value as typeof look.face})}><option value="classic">Classic</option><option value="round">Round</option><option value="soft">Soft</option></select></label>
      <label>Celebration<select value={look.celebration} onChange={event=>appearance({celebration:event.target.value as typeof look.celebration})}><option value="auto">Match my shape</option><option value="roll">Roll</option><option value="dance">Dance</option><option value="bounce">Little bounce</option></select></label>
      <label>Keepsake pin<select value={look.keepsake} onChange={event=>appearance({keepsake:event.target.value as typeof look.keepsake})}><option value="none">None</option><option value="star">Star · a proud moment</option><option value="heart">Heart · something meaningful</option></select></label>
      <label><input type="checkbox" checked={look.sleepy} onChange={event=>appearance({sleepy:event.target.checked})}/> Get sleepy with local time and longer sessions</label><p>After 45 minutes together, or between 10 pm and 6 am on your device, your Buddy looks sleepy. Returning wakes it up. Answer quality and availability stay the same.</p>
    </details>
    <details><summary>How I help & what I remember</summary><p>Tell me “keep answers short,” “give me hints first,” or “use music examples.” Explicit supported requests are remembered for this Buddy across chats. Review or change those defaults here.</p>
      <label>Tone<select value={value.style} onChange={event=>onChange({...value,style:event.target.value as BuddyInput['style']})}>{['calm','encouraging','playful','direct'].map(style=><option key={style}>{style}</option>)}</select></label>
      <label><input type="checkbox" checked={value.concise} onChange={event=>onChange({...value,concise:event.target.checked})}/> Keep answers short</label>
      <label><input type="checkbox" checked={value.examples} onChange={event=>onChange({...value,examples:event.target.checked})}/> Use examples</label>
      <label><input type="checkbox" checked={value.hintsFirst||false} onChange={event=>onChange({...value,hintsFirst:event.target.checked})}/> Give hints first</label>
      <label>Examples from<select value={value.exampleTheme||'general'} onChange={event=>onChange({...value,exampleTheme:event.target.value as BuddyInput['exampleTheme']})}>{['general','music','sports','games','everyday'].map(theme=><option key={theme}>{theme}</option>)}</select></label>
      <label><input type="checkbox" checked={value.rememberPreferences!==false} onChange={event=>onChange({...value,rememberPreferences:event.target.checked})}/> Remember preferences I request in chat</label>
      <button type="button" onClick={()=>onChange({...value,style:'encouraging',concise:true,examples:true,hintsFirst:false,exampleTheme:'general'})}>Reset communication preferences</button>
    </details>
  </div>;
}
