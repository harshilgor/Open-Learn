import {useEffect,useState} from 'react';
import {Image,Text,View} from 'react-native';
import {authenticated,account} from './account';
import type {FlashcardContent} from './flashcard-types';
export function FlashcardImage({image,revealed=false}:{image:FlashcardContent['image'];revealed?:boolean}){
 const [uri,setUri]=useState(''),[ratio,setRatio]=useState(1),[error,setError]=useState('');
 useEffect(()=>{if(!image)return;let active=true;const owner=account()?.owner;void authenticated(`/v1/flashcard-images/${image.versionId}`).then(async response=>{const blob=await response.blob();const reader=new FileReader();reader.onload=()=>{if(active&&account()?.owner===owner){const value=String(reader.result);setUri(value);Image.getSize(value,(w,h)=>{if(active)setRatio(w/h)},()=>undefined)}};reader.readAsDataURL(blob)}).catch(e=>{if(active)setError(e.message)});return()=>{active=false;};},[image?.versionId]);
 if(!image)return null;
 return <View><View style={{width:'100%',aspectRatio:ratio,position:'relative'}}>{uri?<Image source={{uri}} accessibilityLabel={image.altText} style={{width:'100%',height:'100%'}}/>:<Text>{error||'Loading private image…'}</Text>}{!revealed?image.masks.map((mask,i)=><View key={i} accessible={false} style={{position:'absolute',left:`${mask.x*100}%`,top:`${mask.y*100}%`,width:`${mask.width*100}%`,height:`${mask.height*100}%`,backgroundColor:'#222',borderWidth:2,borderColor:'#ddd'}}/>):null}</View><Text style={{color:'#ccc'}}>{image.altText}</Text></View>;
}
