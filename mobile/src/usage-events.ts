export type UsageEventPage={
  events:Array<{id:string;revision:number;kind:string;createdAt:number}>;
  nextRevision:number;latestRevision:number;hasMore:boolean;resnapshotRequired:boolean;
};

export function parseUsageEventPage(value:unknown,afterRevision:number):UsageEventPage|null{
  if(!value||typeof value!=='object')return null;
  const page=value as Partial<UsageEventPage>;
  if(!Number.isSafeInteger(page.nextRevision)||!Number.isSafeInteger(page.latestRevision)||typeof page.hasMore!=='boolean'||typeof page.resnapshotRequired!=='boolean'||!Array.isArray(page.events))return null;
  const next=page.nextRevision as number,latest=page.latestRevision as number;
  if(next<afterRevision||latest<next)return null;
  if(page.resnapshotRequired)return page.events.length===0?{events:[],nextRevision:next,latestRevision:latest,hasMore:false,resnapshotRequired:true}:null;
  let expected=afterRevision;
  const events=[];
  for(const item of page.events){
    if(!item||typeof item!=='object')return null;
    const event=item as UsageEventPage['events'][number];
    if(typeof event.id!=='string'||!event.id||!Number.isSafeInteger(event.revision)||event.revision!==expected+1||typeof event.kind!=='string'||!Number.isFinite(event.createdAt))return null;
    expected=event.revision;events.push(event);
  }
  if(expected!==next||(events.length===0&&(next!==afterRevision||latest!==afterRevision)))return null;
  return{events,nextRevision:next,latestRevision:latest,hasMore:page.hasMore,resnapshotRequired:false};
}
