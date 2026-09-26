(() => {
 const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),8000);
 fetch('/v1/public/app-content',{cache:'no-store',signal:controller.signal}).then(r=>{if(!r.ok)throw Error();return r.json();}).then(data=>{const copy=data.content?.[document.documentElement.lang==='uz'?'uz':'ru'];if(!copy)return;const title=document.querySelector('.page-nearby .intro h1'),hint=document.querySelector('.page-nearby .intro .lead');if(title)title.textContent=copy.title;if(hint)hint.textContent=copy.hint;}).catch(()=>{}).finally(()=>clearTimeout(timer));
})();
