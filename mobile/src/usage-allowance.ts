/** Rounded percentage shared with the web allowance indicator. */
export function usedPercentageLabel(exactPercent:number):string{
  const safe=Math.max(0,Math.min(100,Number.isFinite(exactPercent)?exactPercent:0));
  if(safe===100)return'100%';
  const rounded=Math.round(safe);
  return rounded===0&&safe>0?'Less than 1%':`${Math.min(99,rounded)}%`;
}

export function usageActivityLabel(input:{used:number;held:number;grant:number;status:string}):string{
  const percent=(amount:number)=>`${Math.min(100,Math.max(0,amount/input.grant*100)).toFixed(1).replace(/\.0$/,'')}%`;
  const status=input.status==='in_progress'?'In progress':input.status==='pending'?'Pending':'Settled';
  if(input.used<=0&&input.held>0)return`${percent(input.held)} reserved · ${status}`;
  if(input.used<=0)return`${status} · awaiting usage`;
  return`${percent(input.used)} used${input.held>0?` · ${percent(input.held)} reserved`:''} · ${status}`;
}
