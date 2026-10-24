(function(){
  'use strict';
  const carousel=document.getElementById('mrarMotionCarousel');
  if(!carousel)return;
  const cards=[...carousel.querySelectorAll('.mrar-motion-card')];
  const track=carousel.querySelector('.mrar-motion-track');
  const prev=carousel.querySelector('.mrar-motion-prev');
  const next=carousel.querySelector('.mrar-motion-next');
  const dots=[...document.querySelectorAll('#mrarMotionDots .mrar-motion-dot')];
  const mobileTray=document.getElementById('mrarMobileAnimationTray');
  const modal=document.getElementById('pageModelModal'),modalStage=document.getElementById('pageModelModalStage');
  let fullscreenViewer=null,fullscreenCard=null,fullscreenMenu=null;
  if(!cards.length||!track)return;
  let activeIndex=0,activeMotion=null,motionToken=0;
  const normalize=i=>(i%cards.length+cards.length)%cards.length;
  function settingsFor(card){try{return JSON.parse(card.dataset.animationSettings||'{}').animations||{};}catch(e){return {};}}
  function closeMenus(except=null){
    cards.forEach(card=>{if(card===except)return;const menu=card._mrarMenu||card.querySelector('.mrar-animation-menu'),toggle=card.querySelector('.mrar-animation-menu-toggle');if(menu)menu.hidden=true;if(toggle)toggle.setAttribute('aria-expanded','false');});
  }
  function openMenu(card){
    closeMenus(card);const menu=card._mrarMenu||card.querySelector('.mrar-animation-menu'),toggle=card.querySelector('.mrar-animation-menu-toggle');
    if(menu)menu.hidden=false;if(toggle)toggle.setAttribute('aria-expanded','true');
  }
  function syncMobileMenu(){
    if(!mobileTray)return;
    const isMobile=window.matchMedia('(max-width: 600px)').matches;
    const activeCard=cards[activeIndex];
    cards.forEach(card=>{
      const menu=card._mrarMenu||card.querySelector('.mrar-animation-menu');
      const wrap=card.querySelector('.mrar-motion-viewer-wrap');
      if(!menu)return;
      if(isMobile){
        if(card===activeCard){
          if(menu.parentElement!==mobileTray)mobileTray.appendChild(menu);
          menu.hidden=false;
        }else{
          if(wrap&&menu.parentElement!==wrap)wrap.appendChild(menu);
          menu.hidden=true;
        }
      }else{
        if(wrap&&menu.parentElement!==wrap)wrap.appendChild(menu);
      }
    });
    if(isMobile){
      const activeMenu=activeCard?._mrarMenu||activeCard?.querySelector('.mrar-animation-menu');
      mobileTray.hidden=!activeMenu;
      if(activeMenu)activeMenu.hidden=false;
    }else{
      mobileTray.hidden=true;
    }
  }
  function drawCarousel(openActiveMenu=false){
    track.querySelectorAll('[data-preview-clone="1"]').forEach(el=>el.remove());
    cards.forEach(card=>{card.removeAttribute('data-slot');card.style.gridColumn='';});
    if(cards.length===1){cards[0].dataset.slot='active';cards[0].style.gridColumn='2';}
    else if(cards.length===2){
      const other=normalize(activeIndex+1);
      cards[other].dataset.slot='left';cards[other].style.gridColumn='1';
      cards[activeIndex].dataset.slot='active';cards[activeIndex].style.gridColumn='2';
      const clone=cards[other].cloneNode(true);clone.dataset.previewClone='1';clone.dataset.slot='right';clone.style.gridColumn='3';
      clone.querySelector('.mrar-animation-menu')?.remove();clone.querySelector('.mrar-animation-menu-toggle')?.remove();
      const preview=clone.querySelector('model-viewer');if(preview){preview.removeAttribute('camera-controls');preview.setAttribute('disable-zoom','');preview.setAttribute('disable-pan','');}
      track.append(clone);
    }else{
      const left=normalize(activeIndex-1),right=normalize(activeIndex+1);
      cards[left].dataset.slot='left';cards[left].style.gridColumn='1';
      cards[activeIndex].dataset.slot='active';cards[activeIndex].style.gridColumn='2';
      cards[right].dataset.slot='right';cards[right].style.gridColumn='3';
    }
    prev.hidden=cards.length<2;next.hidden=cards.length<2;
    cards.forEach((card,i)=>{const viewer=card.querySelector('model-viewer');if(!viewer)return;viewer.setAttribute('disable-pan','');if(i===activeIndex){viewer.removeAttribute('disable-zoom');viewer.setAttribute('camera-controls','');}else{viewer.setAttribute('disable-zoom','');viewer.removeAttribute('camera-controls');}});
    dots.forEach((dot,i)=>{const selected=i===activeIndex;dot.classList.toggle('is-active',selected);dot.setAttribute('aria-current',String(selected));});
    closeMenus();
    if(openActiveMenu)openMenu(cards[activeIndex]);
    syncMobileMenu();
  }
  function go(delta){if(activeMotion||cards.length<2)return;activeIndex=normalize(activeIndex+delta);drawCarousel(true);}
  prev.addEventListener('click',()=>go(-1));next.addEventListener('click',()=>go(1));
  dots.forEach((dot,i)=>dot.addEventListener('click',()=>{if(activeMotion)return;activeIndex=normalize(i);drawCarousel(true);}));
  function makeMenu(card){
    const viewer=card.querySelector('model-viewer'),list=(card._mrarMenu||card.querySelector('.mrar-animation-menu'))?.querySelector('.mrar-animation-menu-list');
    if(!viewer||!list||card.dataset.animationsReady==='1'||!viewer.loaded)return;
    card.dataset.animationsReady='1';
    const names=Array.isArray(viewer.availableAnimations)?viewer.availableAnimations:[],saved=settingsFor(card);
    list.replaceChildren();
    names.forEach(name=>{
      const cfg=saved[name]||{},enabled=cfg.enabled!==false;if(!enabled)return;
      const button=document.createElement('button');button.type='button';button.className='mrar-animation-option';button.textContent=name;
      button.dataset.speed=String(Math.min(4,Math.max(.1,Number(cfg.speed)||1)));
      button.dataset.repetitions=String(Math.min(20,Math.max(1,Math.floor(Number(cfg.repetitions)||1))));
      button.dataset.mode=['forward','reverse','pingpong'].includes(cfg.mode)?cfg.mode:'forward';
      button.addEventListener('click',()=>{if(activeMotion||card!==cards[activeIndex])return;runAnimation(card,name,button);});list.append(button);
    });
    // No placeholder text is rendered when the model has no animations or all animations are disabled.
  }
  function finishMotion(token,viewer,finalTime){
    if(!activeMotion||activeMotion.token!==token)return;
    const motion=activeMotion; viewer=motion.viewer||viewer;
    if(motion.onFinished)viewer.removeEventListener('finished',motion.onFinished);
    if(motion.watchdog)cancelAnimationFrame(motion.watchdog);
    try{viewer.pause();viewer.timeScale=1;if(Number.isFinite(finalTime)&&finalTime>=0)viewer.currentTime=finalTime; viewer.animationName=''; viewer.currentTime=0;}catch(e){}
    const card=motion.card;(card._mrarMenu||card).querySelectorAll('.mrar-animation-option').forEach(b=>b.disabled=false);
    if(fullscreenMenu && motion.viewer===fullscreenViewer)fullscreenMenu.querySelectorAll('button').forEach(b=>b.disabled=false);
    activeMotion=null;carousel.classList.remove('is-playing');carousel.querySelectorAll('.mrar-motion-arrow').forEach(b=>b.disabled=false);dots.forEach(b=>b.disabled=false);
  }
  async function runAnimation(card,name,button,viewerOverride=null){
    const viewer=viewerOverride||card.querySelector('model-viewer');if(!viewer||activeMotion||!viewer.loaded)return;
    const token=++motionToken,speed=Math.min(4,Math.max(.1,Number(button.dataset.speed)||1)),repetitions=Math.min(20,Math.max(1,Number(button.dataset.repetitions)||1)),mode=['forward','reverse','pingpong'].includes(button.dataset.mode)?button.dataset.mode:'forward';
    activeMotion={token,card,name,mode,viewer,onFinished:null,watchdog:0};
    carousel.classList.add('is-playing');carousel.querySelectorAll('.mrar-motion-arrow').forEach(b=>b.disabled=true);dots.forEach(b=>b.disabled=true);
    cards.forEach(c=>(c._mrarMenu||c).querySelectorAll('.mrar-animation-option').forEach(b=>b.disabled=true));
    (card._mrarMenu||card).querySelectorAll('.mrar-animation-option').forEach(b=>b.classList.toggle('is-current',b===button));
    try{
      viewer.pause();viewer.animationName=name;
      if(viewer.updateComplete)await viewer.updateComplete;
      await new Promise(resolve=>requestAnimationFrame(()=>resolve()));
      if(!activeMotion||activeMotion.token!==token)return;
      viewer.pause();
      const duration=Number(viewer.duration)||0;
      if(duration<=0){finishMotion(token,viewer,0);return;}
      const finalTime=mode==='forward'?duration:0;
      if(mode==='reverse'){
        // Scrub the timeline backwards while paused. This is reliable even with
        // model-viewer versions where a negative timeScale no longer plays in reverse.
        viewer.timeScale=1;viewer.currentTime=duration;
        const onePassMs=duration/speed*1000,start=performance.now();
        const tick=now=>{
          if(!activeMotion||activeMotion.token!==token)return;
          const elapsed=Math.max(0,now-start),totalMs=onePassMs*repetitions;
          if(elapsed>=totalMs){viewer.currentTime=0;finishMotion(token,viewer,0);return;}
          const withinPass=elapsed%onePassMs;
          viewer.currentTime=Math.max(0,duration-(withinPass/1000)*speed);
          activeMotion.watchdog=requestAnimationFrame(tick);
        };
        activeMotion.watchdog=requestAnimationFrame(tick);
        return;
      }
      viewer.timeScale=speed;viewer.currentTime=0;
      const loops=mode==='pingpong'?repetitions*2:repetitions;
      const expectedMs=duration*loops/speed*1000;
      const onFinished=()=>finishMotion(token,viewer,finalTime);
      activeMotion.onFinished=onFinished;
      viewer.addEventListener('finished',onFinished,{once:true});
      viewer.play({repetitions:loops,pingpong:mode==='pingpong'});
      const started=performance.now();
      const watchdog=now=>{
        if(!activeMotion||activeMotion.token!==token)return;
        if(now-started>expectedMs+1500){finishMotion(token,viewer,finalTime);return;}
        activeMotion.watchdog=requestAnimationFrame(watchdog);
      };
      activeMotion.watchdog=requestAnimationFrame(watchdog);
    }catch(e){finishMotion(token,viewer,0);}
  }
  function closeMrarFullscreen(){
    if(activeMotion && activeMotion.viewer===fullscreenViewer)finishMotion(activeMotion.token,fullscreenViewer,0);
    if(modal){modal.classList.remove('mrar-fullscreen-open');}
    if(modalStage)modalStage.replaceChildren();
    fullscreenViewer=null;fullscreenCard=null;fullscreenMenu=null;
    if(typeof window.closePageModel==='function')window.closePageModel();
  }
  function openMrarFullscreen(btn){
    const card=btn.closest('.mrar-motion-card'); if(!card||!modal||!modalStage)return;
    const source=card.querySelector('model-viewer'); if(!source)return;
    fullscreenCard=card; fullscreenViewer=source.cloneNode(true); fullscreenViewer.removeAttribute('style');
    fullscreenViewer.classList.add('page-model-modal-viewer','mrar-fullscreen-viewer');
    fullscreenViewer.setAttribute('camera-controls','');fullscreenViewer.removeAttribute('disable-pan');fullscreenViewer.removeAttribute('disable-zoom');
    fullscreenViewer.removeAttribute('auto-rotate');
    modalStage.replaceChildren();
    const layout=document.createElement('div');layout.className='mrar-fullscreen-layout';
    const stage=document.createElement('div');stage.className='mrar-fullscreen-model-stage';stage.appendChild(fullscreenViewer);
    const toggle=document.createElement('button');toggle.type='button';toggle.className='mrar-fullscreen-menu-toggle';toggle.setAttribute('aria-label','نمایش فهرست انیمیشن‌ها');toggle.innerHTML='<span></span><span></span><span></span>';
    const menu=document.createElement('div');menu.className='mrar-fullscreen-animation-menu';
    menu.hidden=false;
    toggle.setAttribute('aria-expanded','true');
    const heading=document.createElement('div');heading.className='mrar-fullscreen-menu-heading';heading.textContent='انیمیشن‌ها';menu.appendChild(heading);
    const list=document.createElement('div');list.className='mrar-fullscreen-animation-list';menu.appendChild(list);
    stage.appendChild(toggle);layout.append(stage,menu);modalStage.appendChild(layout);
    toggle.addEventListener('click',()=>{menu.hidden=!menu.hidden;toggle.setAttribute('aria-expanded',String(!menu.hidden));});
    fullscreenMenu=list;
    const build=()=>{
      list.replaceChildren();
      const sourceButtons=[...(card._mrarMenu||card).querySelectorAll('.mrar-animation-option')];
      sourceButtons.forEach(sourceButton=>{
        const b=document.createElement('button');b.type='button';b.className='mrar-animation-option';b.textContent=sourceButton.textContent;
        ['speed','repetitions','mode'].forEach(k=>b.dataset[k]=sourceButton.dataset[k]||({'speed':'1','repetitions':'1','mode':'forward'}[k]));
        b.addEventListener('click',()=>{if(activeMotion)return;list.querySelectorAll('button').forEach(x=>x.disabled=true);runAnimation(card,b.textContent,b,fullscreenViewer);});list.appendChild(b);
      });
    };
    fullscreenViewer.addEventListener('load',build,{once:true});
    modal.classList.add('open','mrar-fullscreen-open');modal.setAttribute('aria-hidden','false');document.body.classList.add('page-model-modal-open');
    const close=modal.querySelector('.page-model-modal-close');if(close){close.onclick=closeMrarFullscreen;}
    const isMobile=window.matchMedia('(max-width: 600px)').matches;
    const modalCard=modal.querySelector('.page-model-modal-card');
    if(modalCard){modalCard.style.width=isMobile?'95vw':'min(94vw,1180px)';modalCard.style.height='70vh';modalCard.style.maxWidth=isMobile?'95vw':'94vw';modalCard.style.maxHeight='70vh';modalCard.style.aspectRatio='auto';}
    if(fullscreenViewer.loaded)build();
  }
  window.openMrarFullscreen=openMrarFullscreen;
  // Keep the generic close button and Escape key aware of the Mr.AR fullscreen layout.
  const genericClose=modal?.querySelector('.page-model-modal-close');
  if(genericClose)genericClose.addEventListener('click',()=>{if(modal.classList.contains('mrar-fullscreen-open'))closeMrarFullscreen();});
  document.addEventListener('keydown',e=>{if(e.key==='Escape'&&modal?.classList.contains('mrar-fullscreen-open'))closeMrarFullscreen();});
  window.addEventListener('resize',()=>{syncMobileMenu();if(!modal?.classList.contains('mrar-fullscreen-open'))return;const isMobile=window.matchMedia('(max-width: 600px)').matches;const c=modal.querySelector('.page-model-modal-card');if(c){c.style.width=isMobile?'95vw':'min(94vw,1180px)';c.style.height='70vh';c.style.maxWidth=isMobile?'95vw':'94vw';c.style.maxHeight='70vh';}});
  cards.forEach((card,index)=>{
    const viewer=card.querySelector('model-viewer'),toggle=card.querySelector('.mrar-animation-menu-toggle'),menu=card._mrarMenu||card.querySelector('.mrar-animation-menu');
    if(!viewer||!toggle||!menu)return; card._mrarMenu=menu;
    const setup=()=>makeMenu(card);viewer.addEventListener('load',setup);if(viewer.loaded)setup();
    toggle.addEventListener('click',e=>{e.stopPropagation();if(card!==cards[activeIndex])return;const opening=menu.hidden;if(opening)openMenu(card);else{menu.hidden=true;toggle.setAttribute('aria-expanded','false');}setup();});
    card.addEventListener('click',e=>{if(e.target.closest('.mrar-animation-menu')||e.target.closest('.mrar-animation-menu-toggle')||e.target.closest('.mrar-model-expand'))return;if(card!==cards[activeIndex]&&!activeMotion){activeIndex=index;drawCarousel(true);}});
  });
  // Delegated click makes the cloned preview card clickable in the two-card carousel case.
  track.addEventListener('click',e=>{const clone=e.target.closest('[data-preview-clone="1"]');if(!clone||e.target.closest('.mrar-model-expand')||activeMotion)return;const idx=Number(clone.dataset.cardIndex);if(Number.isInteger(idx)){activeIndex=normalize(idx);drawCarousel(true);}});
  drawCarousel(true);
  cards.forEach(card=>{const viewer=card.querySelector('model-viewer');if(viewer?.loaded)makeMenu(card);});
})();
