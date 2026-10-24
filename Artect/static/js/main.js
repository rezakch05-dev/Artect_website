window.addEventListener('load',()=>setTimeout(()=>document.querySelector('.loading')?.classList.add('hide'),450));

function initMobileMenu(){
  const toggle=document.querySelector('.mobile-menu-toggle');
  const drawer=document.getElementById('mobileNav');
  const close=drawer?.querySelector('.mobile-nav-close');
  if(!toggle||!drawer)return;
  const setOpen=(open)=>{
    drawer.classList.toggle('open',open);
    drawer.setAttribute('aria-hidden',String(!open));
    toggle.setAttribute('aria-expanded',String(open));
    document.body.classList.toggle('mobile-menu-open',open);
  };
  toggle.addEventListener('click',()=>setOpen(!drawer.classList.contains('open')));
  close?.addEventListener('click',()=>setOpen(false));
  drawer.addEventListener('click',e=>{if(e.target===drawer)setOpen(false);});
  drawer.querySelectorAll('a').forEach(a=>a.addEventListener('click',()=>setOpen(false)));
  document.addEventListener('keydown',e=>{if(e.key==='Escape')setOpen(false)});
}

document.addEventListener('DOMContentLoaded',initMobileMenu);
function openSolution(id){
  const card=document.getElementById('solution-'+id); if(!card)return;
  const mobile=window.matchMedia('(max-width:700px)').matches;
  document.querySelectorAll('.solution-card.active').forEach(x=>x.classList.remove('active'));
  document.querySelectorAll('.mobile-solution-details').forEach(x=>x.remove());
  card.classList.add('active');
  const image=card.dataset.image||'';
  const video=card.dataset.video||'';
  if(mobile){
    const details=document.createElement('div');
    details.className='mobile-solution-details';
    details.innerHTML=`<p class="muted">${card.dataset.sub||''}</p><div class="solution-full">${card.dataset.full||''}</div>${video?`<video controls src="${video}"></video>`:''}`;
    card.appendChild(details);
    card.scrollIntoView({behavior:'smooth',block:'nearest'});
    return;
  }
  const details=document.getElementById('solutionDetails');
  if(!details)return;
  details.innerHTML=`<div class="solution-expanded"><img src="${image}" alt=""><h2>${card.dataset.title||''}</h2><p class="muted">${card.dataset.sub||''}</p><div class="solution-full">${card.dataset.full||''}</div>${video?`<video controls src="${video}"></video>`:''}</div>`;
  details.scrollIntoView({behavior:'smooth',block:'start'});
}
document.addEventListener('DOMContentLoaded',()=>{
  const params=new URLSearchParams(location.search); const id=params.get('open');
  if(id) setTimeout(()=>openSolution(id),150);
});

function applyThemedIcons(root=document){
  const color=getComputedStyle(document.documentElement).getPropertyValue('--icon-color').trim() || getComputedStyle(document.documentElement).getPropertyValue('--primary').trim() || getComputedStyle(document.documentElement).getPropertyValue('--admin-primary').trim() || '#B6E23A';
  const imgs=[...(root.querySelectorAll?.('img.icon-clean')||[])];
  imgs.forEach(img=>{
    const src=img.currentSrc||img.src||img.getAttribute('src');
    if(!src || !/\.svg(?:[?#].*)?$/i.test(src)) return;
    let wrap=img.closest('.themed-icon-wrap');
    if(!wrap){
      wrap=document.createElement('span');
      wrap.className='themed-icon-wrap';
      const cs=getComputedStyle(img);
      wrap.style.display='inline-block';
      wrap.style.width=cs.width;
      wrap.style.height=cs.height;
      wrap.style.flex='0 0 auto';
      wrap.style.position='relative';
      img.parentNode.insertBefore(wrap,img);
      wrap.appendChild(img);
      img.dataset.themedIcon='1';
      img.style.setProperty('opacity','0','important');
      img.style.setProperty('position','absolute','important');
      img.style.setProperty('inset','0','important');
      img.style.setProperty('width','100%','important');
      img.style.setProperty('height','100%','important');
      img.style.setProperty('pointer-events','none','important');
    }
    wrap.style.setProperty('background-color',color,'important');
    wrap.style.setProperty('-webkit-mask-image',`url("${src}")`,'important');
    wrap.style.setProperty('mask-image',`url("${src}")`,'important');
    wrap.style.setProperty('-webkit-mask-repeat','no-repeat','important');
    wrap.style.setProperty('mask-repeat','no-repeat','important');
    wrap.style.setProperty('-webkit-mask-position','center','important');
    wrap.style.setProperty('mask-position','center','important');
    wrap.style.setProperty('-webkit-mask-size','contain','important');
    wrap.style.setProperty('mask-size','contain','important');
  });
}

function initThemedIconObserver(){
  applyThemedIcons();
  const observer=new MutationObserver(mutations=>{
    let needs=false;
    for(const m of mutations){
      if(m.type==='childList' || (m.type==='attributes' && m.attributeName==='src')){needs=true;break;}
    }
    if(needs) requestAnimationFrame(()=>applyThemedIcons());
  });
  observer.observe(document.documentElement,{subtree:true,childList:true,attributes:true,attributeFilter:['src']});
}
document.addEventListener('DOMContentLoaded',initThemedIconObserver);

// Adapt card copy/fade colors to each card image while keeping text readable.
function initImageCardFades(){
  const selectors=[
    '.card',
    '.scenario-card',
    '.work-card',
    '.team-card',
    '.artect-solution-grid article'
  ];
  const cards=[...document.querySelectorAll(selectors.join(','))];
  const mixWithWhite=(r,g,b,amount)=>({
    r:Math.round(r+(255-r)*amount),
    g:Math.round(g+(255-g)*amount),
    b:Math.round(b+(255-b)*amount)
  });
  const apply=card=>{
    const img=card.querySelector(':scope > img:not(.icon-clean), .scenario-image, .work-card-image, .team-image, .application-image');
    if(!img)return;
    const run=()=>{
      try{
        if(!img.naturalWidth||!img.naturalHeight)return;
        const canvas=document.createElement('canvas');
        const w=48,h=48;
        canvas.width=w;canvas.height=h;
        const ctx=canvas.getContext('2d',{willReadFrequently:true});
        if(!ctx)return;
        // Sample the lower part of the image so the copy area visually continues its palette.
        ctx.drawImage(img,0,Math.floor(img.naturalHeight*.68),img.naturalWidth,Math.floor(img.naturalHeight*.32),0,0,w,h);
        const data=ctx.getImageData(0,0,w,h).data;
        let r=0,g=0,b=0,n=0;
        for(let i=0;i<data.length;i+=4){
          if(data[i+3]<180)continue;
          r+=data[i];g+=data[i+1];b+=data[i+2];n++;
        }
        if(!n)return;
        r/=n;g/=n;b/=n;
        // Keep the image character, but lift the color enough for comfortable reading.
        const bg=mixWithWhite(r,g,b,.70);
        const rr=bg.r,gg=bg.g,bb=bg.b;
        const luminance=(0.2126*rr+0.7152*gg+0.0722*bb)/255;
        const text=luminance>.58?'#172019':'#f3f7f2';
        card.style.setProperty('--image-card-bg',`rgb(${rr} ${gg} ${bb})`);
        card.style.setProperty('--image-card-text',text);
        card.style.setProperty('--image-card-muted',luminance>.58?'rgba(23,32,25,.68)':'rgba(243,247,242,.72)');
        card.querySelectorAll('.muted,.work-overlay p').forEach(el=>el.style.color='var(--image-card-muted)');
      }catch(_){/* keep the theme fallback if an image cannot be sampled */}
    };
    if(img.complete)run();else img.addEventListener('load',run,{once:true});
  };
  cards.forEach(apply);
}
document.addEventListener('DOMContentLoaded',initImageCardFades);


function initLoopingVideoImageSlots(){
  const convert=(root=document)=>{
    const candidates=[];
    if(root.matches?.('img')) candidates.push(root);
    candidates.push(...(root.querySelectorAll?.('img[src],img[srcset]')||[]));
    candidates.forEach(img=>{
      const src=img.getAttribute('src')||img.currentSrc||'';
      if(!/\.(mp4|webm|ogv|ogg|mov|m4v)(?:[?#].*)?$/i.test(src) || img.dataset.loopVideoConverted) return;
      const video=document.createElement('video');
      [...img.attributes].forEach(attr=>{
        if(!['src','srcset','alt','loading','decoding'].includes(attr.name)) video.setAttribute(attr.name,attr.value);
      });
      video.src=src;
      video.autoplay=true; video.muted=true; video.loop=true; video.playsInline=true;
      video.setAttribute('aria-label',img.getAttribute('alt')||'ویدئوی تکرارشونده');
      video.dataset.loopVideoConverted='1';
      img.replaceWith(video);
      const play=video.play(); if(play?.catch) play.catch(()=>{});
    });
  };
  convert();
  const observer=new MutationObserver(records=>{
    records.forEach(record=>{
      record.addedNodes.forEach(node=>{if(node.nodeType===1) convert(node);});
      if(record.type==='attributes' && record.target.matches?.('img')) convert(record.target);
    });
  });
  observer.observe(document.documentElement,{subtree:true,childList:true,attributes:true,attributeFilter:['src','srcset']});
}
document.addEventListener('DOMContentLoaded',initLoopingVideoImageSlots);

/* Homepage 3D showcase: animated center-focused carousel and artect-3d-config 1.0.0 UI */
(function(){
 const root=document.getElementById('modelShowcaseCarousel'); if(!root)return;
 const cards=[...root.querySelectorAll('.showcase-card')]; if(!cards.length)return;
 cards.forEach(card=>{const toggle=card.querySelector('.showcase-config-toggle');toggle?.addEventListener('click',event=>{event.preventDefault();event.stopPropagation();if(!window.matchMedia('(min-width:761px)').matches)return;card.classList.toggle('config-collapsed');toggle.setAttribute('aria-expanded',String(!card.classList.contains('config-collapsed')));});});
 let active=0;
 const state=new WeakMap();
 function draw(){
   const count=cards.length;
   cards.forEach((card,i)=>{
     const isActive=i===active;
     const isLeft=count>2 && i===(active-1+count)%count;
     const isRight=count>1 && i===(active+1)%count && !isLeft;
     card.classList.toggle('is-active',isActive); card.classList.toggle('is-left',isLeft); card.classList.toggle('is-right',isRight);
     card.classList.toggle('is-hidden',!isActive&&!isLeft&&!isRight);
     card.setAttribute('aria-hidden',(!isActive&&!isLeft&&!isRight)?'true':'false');
     const viewer=card.querySelector('model-viewer');
     if(viewer){
       if(isActive){viewer.setAttribute('camera-controls','');viewer.setAttribute('auto-rotate','');viewer.style.pointerEvents='auto';}
       else {viewer.removeAttribute('camera-controls');viewer.removeAttribute('auto-rotate');viewer.style.pointerEvents='none';}
     }
   });
   root.parentElement.querySelectorAll('[data-showcase-index]').forEach((b,i)=>b.classList.toggle('active',i===active));
   requestAnimationFrame(sizeMobileCarousel);
 }
 function go(i){active=(i+cards.length)%cards.length;draw();}
 root.parentElement.querySelector('[data-showcase-prev]')?.addEventListener('click',()=>go(active-1));
 root.parentElement.querySelector('[data-showcase-next]')?.addEventListener('click',()=>go(active+1));
 root.parentElement.querySelectorAll('[data-showcase-index]').forEach(b=>b.addEventListener('click',()=>go(+b.dataset.showcaseIndex)));
 root.addEventListener('click',e=>{const c=e.target.closest('.showcase-card');if(c&&!e.target.closest('.showcase-fullscreen-toggle')&&!c.classList.contains('is-active'))go(cards.indexOf(c));});
 // Fullscreen view for the homepage showcase. The existing renderer and configurator nodes are moved,
 // not cloned, so all current configurator state and event handlers remain intact.
 let showcaseModal=null, fullscreenCard=null, fullscreenRestore=null;
 function ensureShowcaseModal(){
   if(showcaseModal)return showcaseModal;
   showcaseModal=document.createElement('div');showcaseModal.className='showcase-fullscreen-backdrop';showcaseModal.hidden=true;
   showcaseModal.innerHTML='<div class="showcase-fullscreen-shell" role="dialog" aria-modal="true" aria-label="نمایش تمام‌صفحه مدل"><button type="button" class="showcase-fullscreen-close" aria-label="بستن نمایش تمام‌صفحه" title="بستن">×</button><div class="showcase-fullscreen-content"></div></div>';
   document.body.appendChild(showcaseModal);
   showcaseModal.querySelector('.showcase-fullscreen-close').addEventListener('click',closeShowcaseFullscreen);
   showcaseModal.addEventListener('click',e=>{if(e.target===showcaseModal)closeShowcaseFullscreen();});
   document.addEventListener('keydown',e=>{if(e.key==='Escape'&&showcaseModal&&!showcaseModal.hidden)closeShowcaseFullscreen();});
   return showcaseModal;
 }
 function openShowcaseFullscreen(card){
   if(!card||fullscreenCard)return;
   const modal=ensureShowcaseModal(),content=modal.querySelector('.showcase-fullscreen-content');
   const wrap=card.querySelector('.showcase-model-wrap'),panel=card.querySelector('.showcase-config-groups');
   if(!wrap||!panel)return;
   fullscreenCard=card;fullscreenRestore={card,wrap,panel,wrapNext:wrap.nextSibling,panelNext:panel.nextSibling,wasActive:card.classList.contains('is-active')};
   const overlayCard=document.createElement('div');overlayCard.className='showcase-fullscreen-card showcase-card is-active';
   overlayCard.append(wrap,panel);content.replaceChildren(overlayCard);
   modal.hidden=false;document.body.classList.add('showcase-fullscreen-open');
   const viewer=wrap.querySelector('model-viewer');if(viewer){viewer.setAttribute('camera-controls','');viewer.style.pointerEvents='auto';requestAnimationFrame(()=>{try{viewer.requestUpdate?.();}catch(_){}});}
 }
 function closeShowcaseFullscreen(){
   if(!showcaseModal||!fullscreenRestore)return;
   const {card,wrap,panel,wrapNext,panelNext}=fullscreenRestore;
   if(wrapNext&&wrapNext.parentNode===card)card.insertBefore(wrap,wrapNext);else card.appendChild(wrap);
   if(panelNext&&panelNext.parentNode===card)card.insertBefore(panel,panelNext);else card.appendChild(panel);
   showcaseModal.querySelector('.showcase-fullscreen-content').replaceChildren();showcaseModal.hidden=true;document.body.classList.remove('showcase-fullscreen-open');
   fullscreenCard=null;fullscreenRestore=null;
   const viewer=card.querySelector('model-viewer');if(viewer){viewer.style.pointerEvents=card.classList.contains('is-active')?'auto':'none';}
 }
 root.querySelectorAll('.showcase-fullscreen-toggle').forEach(btn=>btn.addEventListener('click',e=>{e.preventDefault();e.stopPropagation();openShowcaseFullscreen(btn.closest('.showcase-card'));}));
 // Card navigation is intentionally click-only: touch swipes must not change the active card.
 function sizeMobileCarousel(){
   if(window.matchMedia('(max-width:760px)').matches){
     const activeCard=cards[active];
     if(activeCard){const needed=Math.max(400,activeCard.scrollHeight+4);root.style.height=needed+'px';}
   }else root.style.height='';
 }
 window.addEventListener('resize',sizeMobileCarousel,{passive:true});
 function parseGLBJson(buffer){
   const view=new DataView(buffer); if(view.byteLength<20||view.getUint32(0,true)!==0x46546c67)return null;
   let offset=12; while(offset+8<=view.byteLength){const len=view.getUint32(offset,true),type=view.getUint32(offset+4,true);offset+=8;if(offset+len>view.byteLength)return null;if(type===0x4e4f534a){try{return JSON.parse(new TextDecoder().decode(new Uint8Array(buffer,offset,len)).replace(/\0+$/,'').trim());}catch(_){return null;}}offset+=len;}return null;
 }
 function canonicalModelName(value){return [...String(value||'')].filter(ch=>/[\p{L}\p{N}]/u.test(ch)).join('').toLocaleLowerCase();}
 function resolveTargetEntries(materialMap,target){
   const path=String(target?.nodePath||'').replace(/\/+$/,'');
   const exact=path?materialMap.get(path):null;
   if(exact?.length)return exact;
   const wanted=canonicalModelName(target?.meshName);if(!wanted)return [];
   const candidates=new Map();
   for(const [candidatePath,entries] of materialMap){
     if(entries.some(entry=>canonicalModelName(entry.nodeName)===wanted))candidates.set(candidatePath,entries);
   }
   return candidates.size===1?[...candidates.values()][0]:[];
 }
 function buildMaterialMapFromGLTF(gltf){
   const map=new Map(),nodes=gltf.nodes||[],meshes=gltf.meshes||[],scenes=gltf.scenes||[],scene=scenes[gltf.scene||0];
   const sceneRootName=scene?.name||'Scene';
   function visit(index,path,stack=new Set()){
     const n=nodes[index];if(!n||stack.has(index))return;
     const p=path+'/'+(n.name||('Node_'+index));
     if(Number.isInteger(n.mesh)){
       const mesh=meshes[n.mesh];(mesh?.primitives||[]).forEach((primitive,slot)=>{
         const entry={materialIndex:Number.isInteger(primitive.material)?primitive.material:null,slot,nodeName:n.name||'',path:p,hasMaterial:Number.isInteger(primitive.material),nodeIndex:index,meshIndex:n.mesh,primitiveIndex:slot};
         if(!map.has(p))map.set(p,[]);map.get(p).push(entry);
       });
     }
     const next=new Set(stack);next.add(index);(n.children||[]).forEach(child=>visit(child,p,next));
   }
   (scene?.nodes||[]).forEach(index=>visit(index,'/'+sceneRootName));
   return map;
 }
 async function buildMaterialMap(card){
   const viewer=card.querySelector('model-viewer');
   try{
     const res=await fetch(card.dataset.modelUrl||viewer?.getAttribute('src'));if(!res.ok)throw new Error('فایل مدل قابل دریافت نیست.');
     const buffer=await res.arrayBuffer();const gltf=parseGLBJson(buffer);if(!gltf)throw new Error('ساختار GLB قابل خواندن نیست.');
     let hash='';try{if(window.crypto?.subtle){const digest=await crypto.subtle.digest('SHA-256',buffer);hash=[...new Uint8Array(digest)].map(x=>x.toString(16).padStart(2,'0')).join('');}}catch(_){}
     return {map:buildMaterialMapFromGLTF(gltf),hash,gltf,buffer};
   }catch(e){console.warn('Could not inspect GLB material bindings',e);return {map:new Map(),hash:'',gltf:null,buffer:null};}
 }
 function rebuildGLBWithJSON(buffer,gltf){
   const source=new DataView(buffer),chunks=[];let offset=12;
   while(offset+8<=source.byteLength){
     const length=source.getUint32(offset,true),type=source.getUint32(offset+4,true);offset+=8;
     if(offset+length>source.byteLength)throw new Error('ساختار فایل GLB معتبر نیست.');
     if(type===0x4e4f534a){
       let jsonBytes=new TextEncoder().encode(JSON.stringify(gltf));const paddedLength=Math.ceil(jsonBytes.length/4)*4;
       if(paddedLength!==jsonBytes.length){const padded=new Uint8Array(paddedLength);padded.fill(0x20);padded.set(jsonBytes);jsonBytes=padded;}
       chunks.push({type,bytes:jsonBytes});
     }else chunks.push({type,bytes:new Uint8Array(buffer,offset,length).slice()});
     offset+=length;
   }
   if(!chunks.some(c=>c.type===0x4e4f534a))throw new Error('بخش JSON در فایل GLB پیدا نشد.');
   const totalLength=12+chunks.reduce((sum,c)=>sum+8+c.bytes.length,0),out=new ArrayBuffer(totalLength),view=new DataView(out);let outOffset=12;
   view.setUint32(0,0x46546c67,true);view.setUint32(4,2,true);view.setUint32(8,totalLength,true);
   for(const chunk of chunks){view.setUint32(outOffset,chunk.bytes.length,true);view.setUint32(outOffset+4,chunk.type,true);new Uint8Array(out,outOffset+8,chunk.bytes.length).set(chunk.bytes);outOffset+=8+chunk.bytes.length;}
   return out;
 }
 function isolateTargetMaterials(buffer,gltf,materialMap,cfg){
   if(!buffer||!gltf)return {buffer,map:materialMap,changed:false};
   const materialCloneByTarget=new Map(),meshCloneByNode=new Map();let changed=false;
   // A glTF mesh can itself be instanced by multiple nodes. Give a targeted node its own mesh definition first.
   const meshUsers=new Map();(gltf.nodes||[]).forEach((node,index)=>{if(Number.isInteger(node.mesh)){if(!meshUsers.has(node.mesh))meshUsers.set(node.mesh,[]);meshUsers.get(node.mesh).push(index);}});
   for(const group of (cfg.groups||[]))for(const target of (group.targets||[])){
     const entries=resolveTargetEntries(materialMap,target);
     for(const entry of entries){
       if(!Array.isArray(target.materialSlots)||!target.materialSlots.includes(entry.slot)||!entry.hasMaterial)continue;
       const node=gltf.nodes?.[entry.nodeIndex];if(!node||!Number.isInteger(node.mesh))continue;
       if(!meshCloneByNode.has(entry.nodeIndex)){
         const users=meshUsers.get(node.mesh)||[];
         if(users.length>1){const oldMesh=node.mesh;node.mesh=(gltf.meshes||[]).length;gltf.meshes.push(JSON.parse(JSON.stringify(gltf.meshes[oldMesh])));meshCloneByNode.set(entry.nodeIndex,node.mesh);changed=true;}
         else meshCloneByNode.set(entry.nodeIndex,node.mesh);
       }
       const meshIndex=meshCloneByNode.get(entry.nodeIndex),primitive=gltf.meshes?.[meshIndex]?.primitives?.[entry.primitiveIndex];
       if(!primitive||!Number.isInteger(primitive.material))continue;
       const originalIndex=primitive.material,key=entry.nodeIndex+':'+entry.slot;
       if(materialCloneByTarget.has(key)){primitive.material=materialCloneByTarget.get(key);continue;}
       const originalMaterial=gltf.materials?.[originalIndex];if(!originalMaterial)continue;
       const cloned=JSON.parse(JSON.stringify(originalMaterial));cloned.name=(cloned.name||('material_'+originalIndex))+'__artect_target_'+entry.nodeIndex+'_'+entry.slot;
       const cloneIndex=(gltf.materials||[]).length;gltf.materials.push(cloned);materialCloneByTarget.set(key,cloneIndex);primitive.material=cloneIndex;changed=true;
     }
   }
   if(!changed)return {buffer,map:materialMap,changed:false};
   const transformedBuffer=rebuildGLBWithJSON(buffer,gltf);
   return {buffer:transformedBuffer,map:buildMaterialMapFromGLTF(gltf),changed:true};
 }
 function renderConfig(card){
   const host=card.querySelector('.config-groups-host'); if(!host)return;
   const panel=card.querySelector('.showcase-config-groups');
   host.replaceChildren();
   let cfg; try{cfg=JSON.parse(card.dataset.config||'{}')}catch(e){cfg={};}
   // Models without a real configuration should not reserve or display an empty options panel.
   if(!cfg||!Array.isArray(cfg.groups)||cfg.groups.length===0){panel?.classList.add('is-empty');return;}
   panel?.classList.remove('is-empty');
   if(cfg.format!=='artect-3d-config'||cfg.formatVersion!=='1.0.0'){host.textContent='فرمت کانفیگوریشن پشتیبانی نمی‌شود.';return;}
   const viewer=card.querySelector('model-viewer');
   const modelState={cfg,selected:new Map(),materialMap:null,originals:new Map(),textureCache:new Map()};state.set(card,modelState);
   const applyOption=async(group,option)=>{
     if(!viewer?.model||!modelState.materialMap)return;
     const appearance=option.appearance||{};if(!['color','texture'].includes(appearance.type))return;
     const targets=group.targets||[],indices=new Set();
     targets.forEach(target=>{
       const entries=resolveTargetEntries(modelState.materialMap,target);
       (entries||[]).forEach(entry=>{if(entry.hasMaterial&&Array.isArray(target.materialSlots)&&target.materialSlots.includes(entry.slot))indices.add(entry.materialIndex);});
     });
     const materials=viewer.model.materials||[];
     for(const index of indices){const mat=materials[index];if(!mat)continue;try{
       const pbr=mat.pbrMetallicRoughness;
       if(!modelState.originals.has(index))modelState.originals.set(index,{color:pbr.baseColorFactor?.slice?.()||[1,1,1,1],roughness:pbr.roughnessFactor,metalness:pbr.metallicFactor,texture:pbr.baseColorTexture?.texture||null});
       const original=modelState.originals.get(index);
       // Every choice starts from the material's original state, never from the previously selected option.
       pbr.setBaseColorFactor(original.color.slice());
       pbr.setRoughnessFactor(original.roughness);
       pbr.setMetallicFactor(original.metalness);
       pbr.baseColorTexture.setTexture(original.texture||null);
       if(appearance.type==='color'&&/^#[0-9a-f]{6}$/i.test(appearance.color||'')){
         // A color option must not retain a texture from a previously selected texture option.
         pbr.baseColorTexture.setTexture(null);
         const c=appearance.color; pbr.setBaseColorFactor([parseInt(c.slice(1,3),16)/255,parseInt(c.slice(3,5),16)/255,parseInt(c.slice(5,7),16)/255,1]);
       }else if(appearance.type==='texture'&&appearance.texture?.file&&viewer.createTexture){
         // glTF multiplies base-color texture by baseColorFactor; use white to avoid tint from an old color option.
         pbr.setBaseColorFactor([1,1,1,1]);
         const asset=String(appearance.texture.file).replace(/^\/+/, '');
         const url='/model-config-assets/'+encodeURIComponent(card.dataset.configDir)+'/'+asset.split('/').map(encodeURIComponent).join('/');
         let texture=modelState.textureCache.get(url);if(!texture){texture=await viewer.createTexture(url);modelState.textureCache.set(url,texture);}pbr.baseColorTexture.setTexture(texture);
       }
       if(appearance.roughness!=null)pbr.setRoughnessFactor(Math.max(0,Math.min(1,Number(appearance.roughness))));
       if(appearance.metalness!=null)pbr.setMetallicFactor(Math.max(0,Math.min(1,Number(appearance.metalness))));
     }catch(e){console.warn('Could not apply configurator option to material index '+index,e);}}
   };
   modelState.applyOption=applyOption;
   cfg.groups.slice().sort((a,b)=>(a.order||0)-(b.order||0)).forEach(group=>{
     const row=document.createElement('div');row.className='showcase-config-group';
     const label=document.createElement('div');label.className='showcase-config-label';label.textContent=group.name||'گزینه‌ها';row.append(label);
     const options=document.createElement('div');options.className='showcase-config-options';const ordered=(group.options||[]).slice().sort((a,b)=>(a.order||0)-(b.order||0));
     ordered.forEach((option,optionIndex)=>{
       const btn=document.createElement('button');btn.type='button';btn.className='showcase-config-option';btn.title=option.name||'گزینه';
       const appearance=option.appearance||{},swatch=document.createElement('span');swatch.className='config-swatch';
       if(appearance.type==='color'&&/^#[0-9a-f]{6}$/i.test(appearance.color||''))swatch.style.background=appearance.color;
       else if(appearance.type==='texture'&&appearance.texture?.file){const asset=String(appearance.texture.file).replace(/^\/+/, '');swatch.style.backgroundImage='url("/model-config-assets/'+encodeURIComponent(card.dataset.configDir)+'/'+asset.split('/').map(encodeURIComponent).join('/')+'")';}
       else swatch.textContent='•';
       const txt=document.createElement('span');txt.textContent=option.name||'گزینه';btn.append(swatch,txt);
       btn.addEventListener('click',()=>{
         options.querySelectorAll('button').forEach(x=>x.classList.remove('selected'));btn.classList.add('selected');modelState.selected.set(group.id,option);
         if(modelState.validated&&modelState.materialMap)applyOption(group,option);
       });
       options.append(btn);
       // Every group starts with its first option selected, independent of the editor's display default.
       if(optionIndex===0){btn.classList.add('selected');modelState.selected.set(group.id,option);}
     });
     row.append(options);host.append(row);
   });
   const initialize=async()=>{
     if(modelState.initializing||modelState.validated)return;
     modelState.initializing=true;
     try{
       const inspected=await buildMaterialMap(card);modelState.materialMap=inspected.map;
       const errors=[];const expected=cfg.model?.integrity?.modelHash;const actualHash=card.dataset.modelHash||inspected.hash;
       if(expected&&actualHash&&String(expected).toLowerCase()!==String(actualHash).toLowerCase())errors.push('هش SHA-256 مدل با کانفیگوریشن تطبیق ندارد.');
       if(expected&&!actualHash)errors.push('امکان بررسی هش مدل وجود ندارد.');
       for(const group of cfg.groups){
         for(const target of (group.targets||[])){
           const path=String(target.nodePath||'').replace(/\/+$/,'');const entries=resolveTargetEntries(modelState.materialMap,target);
           if(entries.length===0){errors.push('قطعه با مسیر «'+(path||'نامشخص')+'» پیدا نشد یا نام آن یکتا نیست.');continue;}
           const entryNames=new Set(entries.map(e=>canonicalModelName(e.nodeName)));
           if(target.meshName&&!entryNames.has(canonicalModelName(target.meshName)))errors.push('نام مش در مسیر «'+path+'» مطابقت ندارد.');
           for(const slot of (target.materialSlots||[])){const entry=entries.find(e=>e.slot===slot);if(!entry||!entry.hasMaterial)errors.push('اسلات متریال '+slot+' در قطعه «'+path+'» معتبر نیست.');}
         }
       }
       if(errors.length){host.replaceChildren();const err=document.createElement('div');err.className='showcase-config-error';err.textContent='کانفیگوریشن اجرا نشد: '+[...new Set(errors)].join(' ');host.append(err);return;}
       // glTF materials are shared by material index. Duplicate the material for each configured target
       // primitive so model-viewer edits only that target instead of every mesh using the same material.
       const isolated=isolateTargetMaterials(inspected.buffer,inspected.gltf,modelState.materialMap,cfg);
       if(isolated.changed&&viewer){
         const blobUrl=URL.createObjectURL(new Blob([isolated.buffer],{type:'model/gltf-binary'}));
         await new Promise((resolve,reject)=>{
           let settled=false;const finish=(error)=>{if(settled)return;settled=true;viewer.removeEventListener('load',onLoad);viewer.removeEventListener('error',onError);error?reject(error):resolve();};
           const onLoad=()=>finish();const onError=()=>finish(new Error('مدل سه‌بعدی پس از جداسازی متریال‌ها بارگذاری نشد.'));
           viewer.addEventListener('load',onLoad);viewer.addEventListener('error',onError);viewer.setAttribute('src',blobUrl);
         });
         if(modelState.blobUrl)URL.revokeObjectURL(modelState.blobUrl);modelState.blobUrl=blobUrl;
         modelState.materialMap=isolated.map;
       }else modelState.materialMap=inspected.map;
       modelState.validated=true;
       if(!viewer?.model)return;
       for(const group of cfg.groups){const option=modelState.selected.get(group.id);if(option)await applyOption(group,option);}
     }catch(e){
       console.warn('Could not initialize 3D configurator',e);
       host.replaceChildren();const err=document.createElement('div');err.className='showcase-config-error';err.textContent='اجرای کانفیگوریشن ناموفق بود. لطفاً فایل مدل و کانفیگوریشن را بررسی کنید.';host.append(err);
     }finally{modelState.initializing=false;}
   };
   viewer?.addEventListener('load',initialize);
   if(viewer?.loaded)initialize();
 }
 cards.forEach(renderConfig);draw();
})();
