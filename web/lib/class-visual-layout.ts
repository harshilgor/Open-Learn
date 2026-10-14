import type {VisualSpec} from '@/components/class-visual';
export function layoutClassVisual(spec:VisualSpec){
  const levels=new Map<string,number>(),incoming=new Set(spec.edges.map(edge=>edge.target));
  for(const node of spec.nodes)if(!incoming.has(node.id))levels.set(node.id,0);
  for(let pass=0;pass<spec.nodes.length;pass++)for(const edge of spec.edges)if(levels.has(edge.source)&&!levels.has(edge.target))levels.set(edge.target,Math.min(9,levels.get(edge.source)!+1));
  const levelCounts=new Map<number,number>();for(const level of levels.values())levelCounts.set(level,(levelCounts.get(level)||0)+1);
  const layered=levels.size===spec.nodes.length&&spec.nodes.every(node=>node.x==null&&node.y==null)&&[...levelCounts.values()].every(count=>count<=3);
  const height=Math.max(160,layered?(Math.max(0,...levels.values())+1)*110:Math.ceil(spec.nodes.length/3)*110);
  const groups=new Map<number,string[]>();if(layered)for(const node of spec.nodes){const level=levels.get(node.id)!;groups.set(level,[...(groups.get(level)||[]),node.id]);}
  return {height,positions:new Map(spec.nodes.map((node,index)=>{const level=levels.get(node.id)||0,group=groups.get(level)||[],slot=group.indexOf(node.id);return [node.id,{x:node.x!=null?90+node.x*470:layered?650*(slot+1)/(group.length+1):110+(index%3)*210,y:node.y!=null?35+node.y*(height-70):layered?50+level*110:50+Math.floor(index/3)*110}];}))};
}
