"use client";
import {Buddy as Character, concepts, accessoryChoices} from './buddy-character';
import {defaultAppearance, type BuddyInput} from '@/lib/buddies';
import {useBuddyPresence} from '@/lib/buddy-presence';
import {useState} from 'react';

export const buddyColors={sage:'#B8CFA8',amber:'#F0BA68',blue:'#A9BDE2',rose:'#E99381',violet:'#BEA9DD'};

export function BuddyCustomization({value,onChange}:{value:BuddyInput;onChange:(value:BuddyInput)=>void}) {
  const look={...defaultAppearance,...value.appearance};
  const [previewing,setPreviewing]=useState<number|null>(null);
  const [previewingAccessory,setPreviewingAccessory]=useState<string|null>(null);
  const presence=useBuddyPresence('customization-preview',look.sleepy);
  const appearance=(patch:Partial<typeof look>)=>onChange({...value,appearance:{...look,...patch}});
  const accessoryAppearance=(item:typeof accessoryChoices[number])=>({
    ...look,
    accessories:[...look.accessories.filter(existing=>!(['Beanie','Cap'].includes(item)&&['Beanie','Cap'].includes(existing))),item],
  });
  const toggleAccessory=(item:typeof accessoryChoices[number])=>appearance({accessories:look.accessories.includes(item)
    ?look.accessories.filter(existing=>existing!==item)
    :accessoryAppearance(item).accessories});
  return <div className="buddy-customization">
    <fieldset className="buddy-look-picker">
      <legend>Choose a look</legend>
      <div className="buddy-look-grid">
        {concepts.map((shape,index)=><button type="button" key={shape.name} className="buddy-look-choice" aria-label={`${shape.name}${look.shape===index?' (selected)':''}`} aria-pressed={look.shape===index} onClick={()=>appearance({shape:index})} onPointerEnter={()=>setPreviewing(index)} onPointerLeave={()=>setPreviewing(current=>current===index?null:current)} onFocus={()=>setPreviewing(index)} onBlur={()=>setPreviewing(current=>current===index?null:current)}>
          <span aria-hidden="true"><Character index={index} color={buddyColors[value.color]} {...look} expression={previewing===index?'Happy':look.shape===index?presence:'Neutral'} animated size={52}/></span>
          <span>{shape.name}</span>
        </button>)}
      </div>
    </fieldset>
    <fieldset className="buddy-color-picker">
      <legend>Color</legend>
      <div className="buddy-swatches">{Object.entries(buddyColors).map(([key,color])=><button type="button" key={key} aria-label={`${key} color`} aria-pressed={key===value.color} style={{background:color}} onClick={()=>onChange({...value,color:key as BuddyInput['color']})}/>)}</div>
    </fieldset>
    <details><summary>Outfit & little details</summary>
      <p className="buddy-outfit-hint">Try an accessory on your Buddy. Choose another hat to swap it.</p>
      <div className="buddy-accessory-grid">{accessoryChoices.map(item=>{
        const accessoryLook=accessoryAppearance(item);
        const previewing=previewingAccessory===item;
        return <button type="button" key={item} className="buddy-accessory-choice" aria-pressed={look.accessories.includes(item)} onClick={()=>toggleAccessory(item)} onPointerEnter={()=>setPreviewingAccessory(item)} onPointerLeave={()=>setPreviewingAccessory(current=>current===item?null:current)} onFocus={()=>setPreviewingAccessory(item)} onBlur={()=>setPreviewingAccessory(current=>current===item?null:current)}>
          <span className="buddy-accessory-art" aria-hidden="true"><Character {...accessoryLook} index={look.shape} color={buddyColors[value.color]} expression={previewing?'Happy':'Neutral'} animated size={68}/></span>
          <span className="buddy-accessory-name">{item}</span>
          <span className="buddy-accessory-state">{look.accessories.includes(item)?'On your Buddy':'Add detail'}</span>
        </button>;
        })}</div>
    </details>
  </div>;
}
