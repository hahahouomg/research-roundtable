"use strict";
const $ = id => document.getElementById(id);
const esc = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const paths = {
  folder:'<path d="M3 7h6l2 2h10v10H3z"/><path d="M3 7V5h6l2 2h8v2"/>',
  note:'<path d="M5 5h14v12H9l-4 3z"/><path d="M8 9h8m-8 3h5"/>',
  menu:'<path d="M3 6h18M3 12h18M3 18h18"/>', down:'<path d="m7 10 5 5 5-5"/>',
  arrow:'<path d="M5 12h14m-6-6 6 6-6 6"/>',
  discuss:'<path d="M3 5h13v10H7l-4 3z"/><path d="M18 9h3v11l-4-3h-6"/>',
  settings:'<path d="M4 7h5m4 0h7M4 17h10m4 0h2"/><circle cx="11" cy="7" r="2"/><circle cx="16" cy="17" r="2"/>',
  home:'<path d="M4 10.5 12 4l8 6.5V20h-5.5v-5.5h-5V20H4z"/>',
  up:'<path d="M12 19V5m-6 6 6-6 6 6"/>',
  list:'<path d="M9 7h11M9 12h11M9 17h11M4 7h1M4 12h1M4 17h1"/>',
  grid:'<rect x="4" y="4" width="6.5" height="6.5" rx="1.2"/><rect x="13.5" y="4" width="6.5" height="6.5" rx="1.2"/><rect x="4" y="13.5" width="6.5" height="6.5" rx="1.2"/><rect x="13.5" y="13.5" width="6.5" height="6.5" rx="1.2"/>',
  chevron:'<path d="m9 6 6 6-6 6"/>'
};
const icon = name => '<svg class="ic" aria-hidden="true" viewBox="0 0 24 24">'+paths[name]+'</svg>';
translateShell();
document.querySelectorAll("[data-icon]").forEach(el => el.innerHTML = icon(el.dataset.icon));
const labels = {codex:"Codex",gemini:"Gemini",claude:"Claude"};
const glyph = a => '<span aria-hidden="true" class="glyph '+a+'">'+({codex:"›_",gemini:"✦",claude:"∗"}[a])+'</span>';
const states = {stopped:"已停止",active:"讨论中",chat:"已回复",consensus:"已达成共识",disputed:"仍有分歧",incomplete:"未完成",implementing:"实施中",returned:"实施已返回",inspect:"实施中断",probe:"连接已验证",summarizing:"Gemini 正在总结",closed:"已结束 · 保留分歧"};
const ongoing = s => ["active","implementing","summarizing"].includes(s);
const num = n => Number(n || 0).toLocaleString(uiLanguage());
const displayProject = name => name === "默认" ? t(name) : name;
const displayStage = stage => t(stage.replace(/ v\d+$/, "")) + (stage.match(/ v\d+$/)?.[0] || "");
function displayError(message){
  if(uiLanguage()!=="en" || !message)return message || "";
  const translated=t(message);
  if(translated!==message)return translated;
  const stage=message.match(/^(.*?) 未收齐全部席位回复，已保存现有记录$/);
  return stage?t("{stage} 未收齐全部席位回复，已保存现有记录",{stage:displayStage(stage[1])}):message;
}
const q = new URLSearchParams(location.search);
let project = q.get("project"), sid = q.get("session"), data, serial = 0, pending = false, poll, modalVersion = 0;
let lastSeatMarkup = "", detailOpen = false, noticeTimer, quotaSeq = 0, modalCancelHook = null, claudeSeq = 0, claudeErr = null;
const claudePending = new Map(), navMarkup = new WeakMap();
const motionAllowed = matchMedia("(prefers-reduced-motion: no-preference)");
matchMedia("(prefers-color-scheme: dark)").addEventListener("change",()=>{
  const root=document.documentElement;
  root.classList.add("theme-switching");
  requestAnimationFrame(()=>requestAnimationFrame(()=>root.classList.remove("theme-switching")));
});
let shownDiscussion, lastRenderRecord, offline = false;
function updateMarkup(element, html){
  if(navMarkup.get(element)===html)return;
  element.innerHTML=html;
  navMarkup.set(element,html);
}
function enter(element, kind="content"){
  if(!motionAllowed.matches || document.hidden)return;
  const css=getComputedStyle(document.documentElement);
  element.getAnimations().filter(a=>a.id==="roundtable-entry").forEach(a=>a.cancel());
  const time=parseFloat(css.getPropertyValue("--motion-"+(kind==="overlay"?"overlay":"content")));
  const animation=element.animate([{opacity:0,transform:kind==="overlay"?"translateY(8px) scale(.99)":"translateY(4px)"},{opacity:1,transform:"none"}],{
    duration:time,easing:css.getPropertyValue("--motion-ease").trim()
  });
  animation.id="roundtable-entry";
}
function pollAgain(delay){
  clearTimeout(poll);
  if(!document.hidden)poll=setTimeout(()=>refresh().catch(error),delay);
}
function offlineState(value){
  if(offline===value)return;
  offline=value;
  $("offline").hidden=!value;
  if(value)enter($("offline"));
}
function patchChildren(target, source){
  let at=target.firstChild;
  const key=node=>node.nodeType===1 && (node.getAttribute("data-key") || node.id);
  const keyed=new Map([...target.children].filter(key).map(node=>[key(node),node]));
  for(const fresh of [...source.childNodes]){
    const id=key(fresh);
    const match=at && (id ? keyed.get(id) : at.nodeName===fresh.nodeName && !key(at) ? at : null);
    if(!match){
      target.insertBefore(fresh,at);
      if(fresh.nodeType===1 && fresh.matches(".permission,.lives,.result"))enter(fresh);
      continue;
    }
    if(match!==at)target.insertBefore(match,at);
    at=match.nextSibling;
    if(match.isEqualNode(fresh))continue;
    if(match.nodeType!==1){match.nodeValue=fresh.nodeValue;continue;}
    if(match.dataset.busy)continue;
    for(const attr of [...match.attributes]){
      if(!fresh.hasAttribute(attr.name) && !(attr.name==="open" && match.tagName==="DETAILS"))match.removeAttribute(attr.name);
    }
    for(const attr of fresh.attributes){
      if(match.getAttribute(attr.name)!==attr.value && !(attr.name==="open" && match.tagName==="DETAILS"))match.setAttribute(attr.name,attr.value);
    }
    patchChildren(match,fresh);
  }
  while(at){const next=at.nextSibling;at.remove();at=next;}
}
const draftKey = () => JSON.stringify([project,sid]);
const key = document.querySelector('meta[name="roundtable-key"]').content;
function saveDraft(){try{sessionStorage.setItem("roundtable:draft:"+draftKey(),$("topic").value);}catch{}}
function readDraft(){try{return sessionStorage.getItem("roundtable:draft:"+draftKey())||"";}catch{return "";}}
$("topic").oninput=saveDraft;
async function api(path, body) {
  const options = {headers:{"X-Roundtable":key}};
  if(body){options.method="POST";options.headers["Content-Type"]="application/json";options.body=JSON.stringify(body);}
  const resp = await fetch("/api/"+path, options);
  const result = await resp.json();
  if(!resp.ok) throw Error(result.error || t("请求失败"));
  return result;
}
function notify(msg){const notice=$("notice");notice.textContent=msg;notice.hidden=false;notice.animate([{opacity:.2},{opacity:1}],motionAllowed.matches?150:0);clearTimeout(noticeTimer);noticeTimer=setTimeout(()=>$("notice").hidden=true,5500);}
function error(e){const el=$("formError");if($("modal").open){const hidden=el.hidden;el.textContent=displayError(e.message);el.hidden=false;if(hidden)enter(el);}else notify(displayError(e.message));}
function closeNav(){
  if(document.body.classList.contains("navopen"))$("menu").focus();
  document.body.classList.remove("navopen");
}
function address(){const u=new URL(location.href);u.search="";if(project)u.searchParams.set("project",project);if(sid)u.searchParams.set("session",sid);history.replaceState(null,"",u);}
async function refresh(){
  const stamp=++serial, query=new URLSearchParams();
  if(project)query.set("project",project);if(sid)query.set("session",sid);
  let next;
  try{
    next=await api("state?"+query);
  }catch(ex){
    if(stamp!==serial)return;
    if(ex instanceof TypeError){offlineState(true);pollAgain(2500);return;}
    const missingProject=project && ex.message.startsWith("找不到项目");
    if(missingProject || (sid && ex.message.includes("中找不到记录"))){
      if(missingProject)project="默认";
      sid=null;detailOpen=false;$("topic").value=readDraft();
      notify(t("项目或讨论已移除，已返回项目首页。"));
      return refresh();
    }
    throw ex;
  }
  if(stamp!==serial)return;
  offlineState(false);
  const changed=JSON.stringify(data)!==JSON.stringify(next);
  data=next;project=next.project;address();if(changed)render();
  pollAgain(data.running.length || data.selected?.calls.some(c=>!c.ended)?1200:5000);
}
async function navigate(p,id){
  saveDraft();
  if(p!==project || id!==sid)$("moderator").value="";
  clearTimeout(poll);serial++;project=p;sid=id;detailOpen=false;closeNav();
  $("topic").value=readDraft();
  $("stage").scrollTop=0;
  await refresh();
}
function inline(text){
  return esc(text).replace(/`([^`\n]+)`/g,"<code>$1</code>").replace(/\*\*([^*\n]+)\*\*/g,"<strong>$1</strong>");
}
function prose(text){
  return String(text || "").split(/^```[^\n]*$/m).map((block,i)=>{
    if(i%2)return "<pre>"+esc(block.trim())+"</pre>";
    let list="",html="";
    for(const line of block.split("\n")){
      const item=line.match(/^\s*(?:([-*+])|(\d+)[.)])\s+(.+)$/);
      const next=item?(item[2]?"ol":"ul"):"";
      if(next!==list){
        if(list)html+="</"+list+">";
        if(next)html+="<"+next+">";
        list=next;
      }
      if(item){html+="<li>"+inline(item[3])+"</li>";continue;}
      if(!line.trim())continue;
      const h=line.match(/^(#{1,6})\s+(.+)$/);
      if(h){const level=h[1].length<=2?"h4":"h5";html+="<"+level+">"+inline(h[2])+"</"+level+">";}
      else html+="<p>"+inline(line)+"</p>";
    }
    return html+(list?"</"+list+">":"");
  }).join("");
}
function ballot(text){
  try{const b=JSON.parse(text);if(b.reason && ["accept","object"].includes(b.vote))return (b.vote==="accept"?t("赞成 ·")+" ":t("有异议 ·")+" ")+b.reason;}catch{}
  return text;
}
const levels={low:"低",medium:"中",high:"高",xhigh:"超高",max:"最高",ultra:"极致"};
function modelParts(id){
  const parts=id.split("-");
  const level=id.startsWith("gemini-") && Object.hasOwn(levels,parts.at(-1)) ? parts.pop() : "";
  const name=parts.map(w=>w==="gpt"?"GPT":w==="gemini"?"Gemini":w.charAt(0).toUpperCase()+w.slice(1)).join(" ").replace(/^GPT (\d)/,"GPT-$1");
  return {name,level};
}
function displayModel(id){
  if(!id)return t("自动选择");
  const {name,level}=modelParts(id);
  return name+(level?" · "+t(levels[level]):"");
}
function seatCard(seat){
  const a=seat.agent, m=displayModel(seat.model)+(seat.effort?" · "+t(levels[seat.effort]||seat.effort):"");
  return '<button class="seat" type="button" data-key="seat-'+a+'" data-agent="'+a+'" aria-label="'+esc(t("选择 {agent} 型号",{agent:labels[a]}))+'">'+glyph(a)+'<span class="text"><strong>'+labels[a]+'</strong><small title="'+esc(seat.model||m)+'">'+esc(m)+'</small></span>'+icon("down")+'</button>';
}
function claudeCard(seat){
  const state=claudePending.get(project);
  const enabled=Boolean(seat), checked=state?state.from:enabled;
  const showModel=checked && Boolean(seat);
  const m=showModel ? displayModel(seat.model)+(seat.effort?" · "+t(levels[seat.effort]||seat.effort):"") : "";
  const left=showModel && !state
    ? ('<button class="seat-trigger" type="button" data-agent="claude" aria-label="'+t("选择 Claude 型号和思考强度")+'">')+glyph("claude")+'<span class="text"><strong>Claude</strong><small title="'+esc(seat.model||m)+'">'+esc(m)+'</small></span>'+icon("down")+'</button>'
    : '<div class="seat-trigger '+(showModel?'':'is-off')+'">'+glyph("claude")+'<span class="text"><strong>Claude</strong><small title="'+esc(showModel?seat.model||"":"")+'">'+esc(showModel?m:t("未参与当前项目"))+'</small></span></div>';
  const label=state ? (state.target==="on"?t("校验中…"):t("关闭中…")) : checked ? t("已开启") : t("已关闭");
  return '<div class="seat seat-claude '+(checked?"on":"off")+'" data-key="seat-claude" data-seat="claude">'+left+
    '<button class="seat-switch" type="button" id="claudeToggle" role="switch" aria-checked="'+(checked?"true":"false")+'"'+(state?' disabled aria-busy="true"':'')+
    ' aria-label="'+esc(t("项目「{project}」的 Claude 席位开关",{project:displayProject(project)}))+'" data-claude-toggle>'+
    '<span class="switch-track" aria-hidden="true"><span class="switch-thumb"></span></span>'+
    '<span class="switch-label">'+label+'</span></button></div>';
}
function render(){
  $("projectTitle").textContent=displayProject(project);
  $("liveNav").hidden=!data.running.length;
  updateMarkup($("liveItems"),data.running.map(r=>'<button class="navitem" data-live="'+esc(r.id)+'" data-owner="'+esc(r.project)+'"><span class="livepip"></span><span class="name">'+esc(r.topic)+'</span>'+(r.awaiting?('<small>'+t("待确认")+'</small>'):'')+'</button>').join(""));
  updateMarkup($("projects"),data.projects.map(p=>'<button class="navitem '+(p===project?'on':'')+'" data-project="'+esc(p)+'">'+icon("folder")+'<span class="name">'+esc(displayProject(p))+'</span></button>').join(""));
  updateMarkup($("history"),data.sessions.map(s=>'<button class="navitem historyitem '+(sid===s.id?'on':'')+'" data-session="'+esc(s.id)+'" title="'+esc(s.topic)+'">'+icon("note")+'<span class="name">'+esc(s.topic)+'</span></button>').join("")||('<p class="emptyrail">'+t("还没有讨论")+'</p>'));
  const claudeSeat=data.seats.find(s=>s.agent==="claude"), claudeEnabled=Boolean(claudeSeat);
  const seatMarkup=data.seats.filter(s=>s.agent!=="claude").map(seatCard).join("")+claudeCard(claudeSeat);
  if(seatMarkup!==lastSeatMarkup){
    const template=document.createElement("template");template.innerHTML=seatMarkup;
    patchChildren($("seats"),template.content);lastSeatMarkup=seatMarkup;
  }
  const showClaudeErr=claudeErr && claudeErr.project===project;
  $("claudeError").hidden=!showClaudeErr;
  $("claudeError").textContent=showClaudeErr?claudeErr.message:"";
  const modeEl=$("mode"), claudeMode=modeEl.querySelector('[value="claude"]');
  if(claudeEnabled){if(claudeMode)claudeMode.text=t("只问 Claude");else modeEl.add(new Option(t("只问 Claude"),"claude"));}
  else{if(modeEl.value==="claude")modeEl.value="both";if(claudeMode)claudeMode.remove();}
  const moderator=$("moderator"), claudeModerator=moderator.querySelector('[value="claude"]');
  if(claudeEnabled && !claudeModerator)moderator.add(new Option("Claude","claude"));
  if(!claudeEnabled && claudeModerator){if(moderator.value==="claude")moderator.value="";claudeModerator.remove();}
  $("moderatorField").hidden=modeEl.value!=="both";
  const record=data.selected;
  $("stage").classList.toggle("reading",Boolean(record));
  $("conversation").hidden=!record;
  if(record && record!==lastRenderRecord)renderDiscussion(record);
  if(shownDiscussion!==record?.id){
    enter(record?$("conversation"):$("intro"));
    shownDiscussion=record?.id;
  }
  lastRenderRecord=record;
  const busy=ongoing(record?.state);
  $("send").disabled=pending||busy;
  $("send").innerHTML=(pending?t("正在发送…"):busy?t("进行中"):record?t("继续提问"):$("mode").value==="both"?t("开始讨论"):t("发送问题"))+" "+icon("arrow");
  $("topic").placeholder=record?t("补充条件，或继续追问…"):t("写下你的问题…");
}
function finalDraft(s){
  return s.calls.find(c=>c.stage==="最终方案撰写" && c.agent==="gemini" && c.ended && !c.error)?.reply;
}
function closingDraft(s){
  return s.calls.find(c=>c.stage==="讨论总结" && c.agent==="gemini" && c.ended && !c.error)?.reply;
}
function permissionCard(req, expanded){
  const d=req.details, input=d.rawInput||d.args||{};
  const agent=labels[req.agent]||t("席位");
  const command=input.CommandLine||input.command;
  const summary=input.toolSummary||d.title||d.kind||t("工具请求");
  const detail=Object.fromEntries(Object.entries(d).filter(([k])=>k!=="cwd"));
  return '<section class="permission" data-key="permission-'+req.id+'" aria-label="'+esc(agent)+(' '+t("工具授权")+'"><h3>')+esc(agent)+(' '+t("正在等你确认")+'</h3>')+
    '<p>'+esc(displayStage(req.stage))+' · '+esc(summary)+('</p><p class="hint">'+t("工作目录 ·")+' ')+esc(d.cwd)+'</p>'+
    (typeof command==="string"?'<pre>'+esc(command)+'</pre>':'')+
    '<details data-request-detail="'+req.id+'" '+(expanded||!command?'open':'')+('><summary>'+t("完整工具参数")+'</summary><pre>')+esc(JSON.stringify(detail,null,2))+'</pre></details>'+
    '<div class="dialogactions"><button class="quiet" data-permission="'+req.id+('" data-choice="deny">'+t("拒绝并停止本席")+'</button>')+
    (req.can_allow?'<button class="primary" data-permission="'+req.id+('" data-choice="allow">'+t("仅允许这一次")+'</button>'):'')+'</div></section>';
}
const failureLabels={
  timeout:"调用超时",quota:"额度或频率受限",provider_safety:"服务方内容安全限制",
  tool_permission:"工具权限受限",account_access:"账号或连接核验失败",interrupted:"调用中断",provider_error:"调用失败"
};
const evidenceKinds={
  observation:"报告的观测",reference:"参考来源",inference:"推断",untested:"尚未验证"
};
function evidenceCard(review){
  const votes=Object.values(review.votes), accepted=votes.filter(v=>v==="accept").length;
  const objections=votes.length-accepted, remaining=review.items.filter(item=>item.blocking && !item.response).length;
  const status = [
    review.version && t("表决")+" v"+review.version,
    review.version && t("赞成 {count}/{total}",{count:accepted,total:review.seats}),
    objections && t("反对 {count}",{count:objections}),
    remaining && t("{count} 项阻塞待回应",{count:remaining})
  ].filter(Boolean).join(" · ");
  const items=review.items.map(item=>{
    const facts=[["来源",item.source],["验证条件",item.check],["主持人回应",item.response]]
      .filter(([,value])=>Boolean(value)).map(([key,value])=>'<dt>'+t(key)+'</dt><dd>'+esc(value)+'</dd>').join("");
    return '<li data-key="evidence-'+esc(item.id)+'"><div class="evidence-meta"><b>'+esc(item.id)+'</b> · '+
      esc(labels[item.agent])+' · '+t(evidenceKinds[item.kind])+' · '+t(item.blocking?"阻塞项":"建议")+'</div>'+
      '<p>'+esc(item.claim)+'</p>'+(facts?'<dl>'+facts+'</dl>':'')+
      (item.blocking && !item.response?'<small>'+t("待主持人回应")+'</small>':'')+'</li>';
  }).join("");
  return '<details class="review-card" data-key="evidence"><summary>'+t("评议与表决")+
    (status?'<small>'+esc(status)+'</small>':'')+'</summary><p class="hint">'+t("评议者报告 · 未由圆桌独立核实")+'</p>'+
    (items?'<ul class="evidence-list">'+items+'</ul>':'<p class="hint">'+t("暂无带编号的发现。")+'</p>')+
    (review.original.length?'<p class="hint">'+t("评议原文见发言记录")+' · '+review.original.map(agent=>esc(labels[agent])).join(", ")+'</p>':'')+
    '</details>';
}
function inputsCard(change){
  const paths=change.paths||[];
  return '<section class="result dispute-panel" data-key="changedInputs"><h3>'+
    t({missing_baseline:"旧记录缺少工作输入基线",unavailable:"原工作目录不可用"}[change.reason]||"工作输入发生变化")+'</h3><p>'+
    t(change.reason==="unavailable"?"请到项目设置重新绑定工作目录，再开始关联讨论。":"保留原有讨论和表决。请用当前文件开始关联讨论。")+'</p>'+
    (paths.length?'<ul>'+paths.map(path=>'<li><code>'+esc(path)+'</code></li>').join("")+'</ul>':'')+
    (change.count>paths.length?'<p class="hint">'+t("还有 {count} 个项目变更",{count:change.count-paths.length})+'</p>':'')+
    '<div class="discussion-actions"><button id="continueDispute" class="primary">'+t("带着分歧继续讨论")+'</button></div></section>';
}
function patchCard(s){
  const text=s.state==="returned"?"先在目标目录运行补丁检查，通过后再应用。":"实施未完成。以下补丁只包含已经产生的改动。";
  return '<section class="result" data-key="implementation-patch"><h3>'+t("实施预览")+'</h3>'+
    (s.has_patch?'<p class="hint">'+t(text)+'</p><button id="exportPatch" class="quiet">'+t("下载补丁")+
      '</button><details id="inspectPatch"><summary>'+t("查看改动")+'</summary><pre></pre></details>'+
      (s.state==="returned"?'<pre>git apply --check implementation.patch\ngit apply implementation.patch</pre>':''):
      '<p class="hint">'+t("未生成文件补丁。")+'</p>')+'</section>';
}
function renderDiscussion(s){
  const calls=s.calls;
  const lastReply=stage=>calls.filter(c=>c.stage===stage && c.reply).slice(-1)[0]?.reply;
  const reports=calls.filter(c=>["实施","集成复核"].includes(c.stage) && c.reply).map(c=>{
    let report=c.reply;
    try{report=JSON.parse(c.reply).report||report;}catch{}
    return labels[c.agent]+" · "+displayStage(c.stage)+" · "+report;
  });
  const draft=finalDraft(s), summary=closingDraft(s);
  const result=reports.length?reports.join("\n\n"):summary||draft||s.plan||lastReply("单聊");
  const resultLabel=reports.length?t("实施报告"):summary?t("讨论总结"):draft?t("最终方案 · Gemini 执笔"):s.state==="consensus"?t("共识方案"):s.plan?t("候选方案"):t("回复");
  const failures=calls.filter((c,i)=>c.error && !calls.slice(i+1).some(n=>n.stage===c.stage && n.agent===c.agent && n.ended && !n.error));
  const lastStage=calls[calls.length-1]?.stage;
  const totals=calls.map(c=>JSON.parse(c.usage||"{}").total).filter(Number.isFinite);
  const used=totals.length?num(totals.reduce((sum,n)=>sum+n,0))+" tokens":t("用量待回报");
  const stateStyle=["consensus","returned","chat","probe"].includes(s.state)?"done":["disputed","closed","inspect","incomplete"].includes(s.state)?"warn":"";
  const busy=ongoing(s.state);
  const previewStatus=s.implementation_preview && ({implementing:"预览进行中",returned:"预览已生成",inspect:"预览已中断"}[s.state]);
  const concise=s.topic.length>95 ? (s.topic.match(/^.{8,75}?[？。！？]/u)?.[0] || s.topic.slice(0,76)+"…") : s.topic;
  let html='<div class="topline"><span class="state '+stateStyle+'" aria-live="polite">'+esc(s.stop_requested&&busy?t("正在停止"):t(previewStatus||states[s.state]||s.state))+(busy&&lastStage?' · '+esc(displayStage(lastStage)):'')+'</span>';
  if(!busy)html+=('<button class="quiet jump-reply" id="jumpReply">'+t("去追问")+'</button>');
  if(s.moderator)html+=('<span class="hint moderator-label">'+t("主持 ·")+' ')+esc(labels[s.moderator])+'</span>';
  html+= busy ? '<button class="stop" id="stop" '+(s.stop_requested?'disabled':'')+'>'+ (s.stop_requested?t('正在停止…'):s.state==="implementing"?t(s.implementation_preview?"停止预览":"停止实施"):s.state==="summarizing"?t('停止总结'):t('停止本轮'))+'</button>' : "";
  html+='</div><h1 class="topic-title">'+esc(concise)+'</h1>';
  if(s.state==="active" && s.plan_versions)html+='<p class="hint">'+esc(t("最多表决 {count} 版",{count:s.plan_versions}))+'</p>';
  for(const request of s.permissions||[]){
    const expanded=document.querySelector('[data-request-detail="'+request.id+'"]')?.open;
    html+=permissionCard(request,expanded);
  }
  if(s.review)html+=evidenceCard(s.review);
  if(s.input_change)html+=inputsCard(s.input_change);
  if(concise!==s.topic)html+=('<details class="original" data-key="source-topic"><summary>'+t("原始议题")+'</summary><p class="prose">')+esc(s.topic)+'</p></details>';
  if(busy || s.state==="stopped"){
    if(s.state==="stopped")html+='<p class="hint stopnote">'+(s.workspace?t(s.implementation_preview?"预览已停止，已收到的实施报告仍保留。":"实施已停止，请核对目录中已经写入的文件。"):t('本轮已停止。已收到的发言保存在下方，可以继续追问。'))+'</p>';
    const live=calls.filter(c=>c.stage===lastStage);
    if(live.length)html+='<div class="lives">'+live.map(c=>{
      const approval=!c.ended && s.permissions?.some(r=>r.stage===c.stage && r.agent===c.agent);
      const waiting=!c.ended&&!c.reply, status=approval?t('待你确认'):c.error?t('已中断'):c.ended?t('已发言'):c.reply?t('发言中'):t('等待发言');
      const reply=c.stage.startsWith("表决")?ballot(c.reply):c.reply;
      return '<article data-key="live-'+c.id+'" class="livecard '+(waiting?'waiting':'')+'"><div class="callhead">'+glyph(c.agent)+'<b>'+labels[c.agent]+'</b><small>'+status+'</small></div>'+
        (reply?'<div class="prose">'+prose(reply)+'</div>':'<div class="waitline" aria-hidden="true"></div>')+'</article>';
    }).join("")+'</div>';
  }
  if(s.workspace)html+='<p class="hint">'+t(s.implementation_preview?"预览目标 ·":"实施目录 ·")+' '+esc(s.workspace)+'</p>';
  if(s.implementation_preview && !busy)html+=patchCard(s);
  if((summary||s.plan) && !busy)html+='<button class="quiet" id="exportPlan">'+t(summary?"下载讨论总结":["disputed","closed","incomplete"].includes(s.state)?"下载候选方案":"下载方案")+'</button>';
  if(draft && !busy)html+='<button class="quiet" id="exportPDF">'+(s.has_pdf?t('下载图文 PDF'):t('请 Gemini 排版 PDF'))+'</button>';
  if(!busy)html+='<button class="quiet" id="discussionFolder">'+icon("folder")+(' '+t("记录文件夹")+'</button>');
  if(calls.length && !busy)html+=('<button class="quiet" id="exportRecord">'+t("下载讨论记录")+'</button>');
  if(s.parent)html+='<button class="quiet" data-session="'+esc(s.parent)+('">'+t("← 上一轮讨论")+'</button>');
  if(s.state==="closed" || s.state==="summarizing")html+=('<p class="summary-note">'+t("本轮未达成共识。原始提案、异议与表决已保留。")+'</p>');
  if(s.state==="disputed"){
    html+=('<section class="result dispute-panel" data-key="disputes"><h3>'+t("表决结束，仍有分歧")+'</h3>')+
      calls.filter(c=>c.stage===lastStage&&c.reply).map(c=>'<p class="prose">'+esc(labels[c.agent])+' · '+esc(ballot(c.reply))+'</p>').join("")+
      ('<div class="discussion-actions"><button id="continueDispute" class="primary">'+t("带着分歧继续讨论")+'</button>')+
      ('<button id="closeDiscussion" class="quiet">'+t("结束并请 Gemini 总结")+'</button></div></section>');
  }
  if(result)html+='<article class="result" data-key="result"><h3>'+resultLabel+'</h3><div class="prose">'+prose(result)+'</div></article>';
  if(draft)html+=('<details data-key="approved-plan"><summary>'+t("全体表决通过的原稿及分工")+'</summary><div class="prose">')+prose(s.plan)+'</div></details>';
  if(summary && s.plan)html+=('<details data-key="last-candidate"><summary>'+t("最后一版候选方案")+'</summary><div class="prose">')+prose(s.plan)+'</div></details>';
  if(s.state==="closed" && !summary)html+=('<button id="closeDiscussion" class="quiet">'+t("重试 Gemini 总结")+'</button>');
  if(s.notice)html+='<p class="hint">'+esc(s.notice)+'</p>';
  if(s.failure && !s.input_change && (s.state!=="incomplete" || !failures.length))html+='<p class="formerror">'+esc(displayError(s.failure))+'</p>';
  if(!s.input_change && ((s.state==="incomplete" && (s.can_resume || calls.some(c=>c.stage==="独立提案"))) || (s.state==="consensus" && !draft && calls.some(c=>c.stage==="最终方案撰写" && c.error))))html+=('<button id="resumeDiscussion" class="quiet">'+t("从中断阶段续跑")+'</button>');
  if(s.state==="incomplete"&&!s.failure&&!failures.length)html+=('<p class="hint">'+t("本轮未收齐有效回复。可展开逐轮发言，或在「订阅额度」中查看账号额度。")+'</p>');
  if(failures.length && s.state!=="stopped"){
    html+=('<section class="call-errors" data-key="call-errors" aria-label="'+t("调用问题")+'">')+failures.map(c=>{
      const title=t(failureLabels[c.failure_kind]||failureLabels.provider_error);
      return '<details data-key="call-error-'+c.id+'"><summary>'+esc(labels[c.agent])+' · '+esc(displayStage(c.stage))+' · '+esc(title)+'</summary>'+
        (displayError(c.error)===title?'':'<p class="prose">'+esc(displayError(c.error))+'</p>')+'</details>';
    }).join("")+
    (failures.some(c=>c.failure_kind==="quota")?('<button class="quiet" id="failureQuota">'+t("查看订阅额度")+'</button>'):'')+
    (failures.some(c=>c.failure_kind==="timeout")?('<button class="quiet" id="failureTimeout">'+t("调整单次超时")+'</button>'):'')+
    '</section>';
  }

  if(s.state==="consensus")html+=('<div class="discussion-actions"><button id="implement" class="primary">'+t("按分工实施")+' ')+icon("arrow")+'</button></div>';
  if(calls.length)html+='<details id="transcript"'+(detailOpen?' open':'')+'><summary>'+esc(t("逐轮发言 · {count} 次调用 · {usage}",{count:calls.length,usage:used}))+'</summary>'+(detailOpen?calls.map(c=>{
    const tokens=JSON.parse(c.usage||"{}").total, reply=c.stage.startsWith("表决")?ballot(c.reply):c.reply;
    return '<article data-key="call-'+c.id+'" class="call"><div class="callhead"><b>'+esc(labels[c.agent])+'</b>'+esc(displayStage(c.stage))+'<small>'+esc([c.model,c.effort].filter(Boolean).join(" · "))+(tokens==null?"":" · "+num(tokens)+" tokens")+'</small></div><div class="prose">'+prose((c.error?displayError(c.error)+'\n':'')+(reply||(c.ended?t("无回复"):t("等待回复…"))))+'</div></article>';
  }).join(""):"")+'</details>';
  const loadedPatch=$("inspectPatch")?.querySelector("pre")?.textContent;
  const target=$("conversation"), template=document.createElement("template");
  template.innerHTML=html;
  if(loadedPatch && shownDiscussion===s.id && s.has_patch)template.content.querySelector("#inspectPatch pre").textContent=loadedPatch;
  if(shownDiscussion!==s.id)target.replaceChildren(template.content);
  else patchChildren(target,template.content);
  const patch=$("inspectPatch");
  if(patch){patch.ontoggle=async()=>{
    const pre=patch.querySelector("pre");
    if(!patch.open || pre.textContent)return;
    pre.dataset.busy="true";
    try{
      const response=await fetchPatch(s.id,true), result=await response.json();
      pre.textContent=result.patch+(result.truncated?"\n\n"+t("预览已截断，请下载完整补丁。"):"");
    }catch(ex){error(ex);}
    finally{delete pre.dataset.busy;}
  };}
  const tr=$("transcript");if(tr)tr.ontoggle=()=>{
    if(tr.isConnected && detailOpen!==tr.open){detailOpen=tr.open;renderDiscussion(s);}
  };
}
function dialog(title,html){
  const d=$("modal");modalCancelHook=null;d.classList.remove("wide");
  $("modalBody").onclick=null;$("modalTitle").textContent=title;$("modalBody").innerHTML=html;$("formError").hidden=true;
  if(!d.open)d.showModal();
  enter(d,"overlay");
  return ++modalVersion;
}
function dismiss(){modalCancelHook=null;$("modal").classList.remove("wide");modalVersion++;$("modal").close();}
$("closeModal").onclick=dismiss;
$("modal").addEventListener("cancel",e=>{if(modalCancelHook){e.preventDefault();modalCancelHook();}});
$("modal").addEventListener("close",()=>{if($("modal").open)return;modalCancelHook=null;$("modal").classList.remove("wide");modalVersion++;});
$("modal").addEventListener("click",e=>{if(e.target===$("modal")){const r=$("modal").getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)dismiss();}});
async function pickModel(agent){
  const p=project, seat=data.seats.find(s=>s.agent===agent);
  if(!seat)return;
  const version=dialog(t(agent==="gemini"?"选择 {agent} 型号":"选择 {agent} 型号和思考强度",{agent:labels[agent]}),('<input class="field" id="search" aria-label="'+t("搜索型号")+'" placeholder="'+t("搜索型号…")+'" autocomplete="off"><div class="options" id="choices"><p class="hint">'+t("正在读取本机 CLI 的型号清单…")+'</p></div>'));
  $("search").focus();
  try{
    const catalog=await api("catalog?agent="+agent);
    const options=catalog.models;
    if(version!==modalVersion)return;
    const draw=()=>{
      const query=$("search").value.trim().toLowerCase();
      const rows=new Map();
      for(const id of options){
        const {name,level}=modelParts(id);
        if(!(id+" "+name+" "+(t(levels[level])||"")).toLowerCase().includes(query))continue;
        if(!rows.has(name))rows.set(name,[]);
        rows.get(name).push({id,level});
      }
      let html=query?"":('<button class="option reset-model" data-value="default">'+t("使用默认型号")+'</button>');
      for(const [name,variants] of rows){
        if(agent!=="gemini"){
          for(const {id} of variants){
            const effortButtons=["default",...(catalog.efforts[id]||[])].map(v=>
              '<button class="level" data-value="'+esc(id)+'" data-effort="'+esc(v)+'" aria-label="'+esc(name+" "+t("思考强度")+" "+t(levels[v]||v))+'" aria-pressed="'+(seat.model===id && (seat.effort||"default")===v)+'">'+esc(t(v==="default"?"默认":levels[v]||v))+'</button>').join("");
            html+='<div class="variant"><strong>'+esc(name)+'</strong><div>'+effortButtons+'</div></div>';
          }
        }else if(variants.every(v=>v.level)){
          variants.sort((a,b)=>Object.keys(levels).indexOf(a.level)-Object.keys(levels).indexOf(b.level));
          html+='<div class="variant"><strong>'+esc(name)+'</strong><div>'+variants.map(v=>
            '<button title="'+esc(v.id)+'" aria-label="'+esc(name+" · "+t(levels[v.level]))+'" aria-pressed="'+(seat.model===v.id)+'" class="level" data-value="'+esc(v.id)+'">'+t(levels[v.level])+'</button>').join("")+'</div></div>';
        }else{
          html+=variants.map(v=>'<button class="option '+(v.id===seat.model?'active':'')+'" title="'+esc(v.id)+'" data-value="'+esc(v.id)+'">'+esc(displayModel(v.id))+(v.id===seat.model?'<b>✓</b>':'')+'</button>').join("");
        }
      }
      $("choices").innerHTML=html||('<p class="hint">'+t("没有匹配的型号")+'</p>');
    };
    draw();$("search").oninput=draw;
    $("choices").onclick=async e=>{
      const b=e.target.closest("[data-value]");if(!b)return;
      try{await api("model",{project:p,agent,model:b.dataset.value,effort:b.dataset.effort||""});dismiss();await refresh();}catch(ex){error(ex);}
    };
  }catch(e){if(version===modalVersion){$("choices").textContent="";error(e);}}
}
function projectDialog(create, openRunSettings=false){
  closeNav();
  dialog(create?t("新建项目"):t("项目设置"),'<form id="projectForm">'+(create?('<label for="pName">'+t("项目名称")+'</label><input id="pName" class="field" placeholder="'+t("例如，文献检索")+'" required maxlength="120">'):'<p class="hint">'+esc(displayProject(project))+'</p>')+
    ('<label for="pPath">'+t("工作目录"))+(create?t('（可选）'):'')+'</label><input id="pPath" class="field" value="'+esc(create?"":data.path)+'" placeholder="'+(create?t('留空自动创建'):t('输入已有目录的路径'))+'" '+(create?"":"required")+('><p class="hint">'+t("讨论时各席使用此目录的实验副本。")+'</p><div class="dialogactions"><button class="primary">')+(create?t('创建项目'):t('保存目录'))+'</button></div></form>');
  directoryPicker("pPath");
  if(!create){
    const timeout=data.default_timeout_seconds;
    const fallback=timeout===null?t('请填写分钟数'):t(timeout%60===0?"默认 {number} 分钟":"默认 {number} 秒",{number:timeout%60===0?timeout/60:timeout});
    $("modalBody").insertAdjacentHTML("beforeend",
      ('<section class="project-storage"><h3>'+t("讨论数据")+'</h3><button type="button" class="quiet" id="projectFolder">')+icon("folder")+(' '+t("项目记录文件夹")+'</button></section>')+
      '<details class="advanced"'+(openRunSettings?' open':'')+('><summary>'+t("运行设置")+'</summary><form id="preferences">')+
      ('<label for="roundCount">'+t("候选方案表决上限")+'</label><select class="field" id="roundCount"><option value="1">'+t("1 版")+'</option><option value="2">'+t("2 版（默认）")+'</option><option value="3">'+t("3 版")+'</option></select>')+
      ('<p class="hint">'+t("适用于新讨论，全票通过即进入定稿。")+'</p>')+
      ('<label for="timeout">'+t("单次调用超时（分钟）")+'</label><input id="timeout" class="field" type="number" min="1" max="120" placeholder="')+fallback+'" value="'+esc(data.call_minutes??"")+'">'+
      ('<p class="hint">'+t("每个席位在一个阶段的一次调用，讨论和实施共用。等待网页工具确认时暂停计时。")+'</p>')+
      ('<div class="tool-settings"><label for="toolMode">'+t("三席工具策略")+'</label><select class="field" id="toolMode"><option value="cli">'+t("跟随 CLI")+'</option><option value="auto">'+t("优先 Auto")+'</option></select>')+
      ('<p class="hint">'+t("Auto 取决于 CLI 与账号。工具仍受各席的工作目录和权限限制。")+'</p></div>')+
      ('<div class="dialogactions"><button class="primary">'+t("保存运行设置")+'</button></div></form></details>'));
    $("modalBody").insertAdjacentHTML("beforeend",('<button class="quiet" type="button" id="claudeConfig">'+t("Claude 出口设置")+'</button>'));
    $("toolMode").value=data.tool_mode;
    $("roundCount").value=String(data.plan_versions);
    $("preferences").onsubmit=async e=>{
      e.preventDefault();
      const b=e.submitter;b.disabled=true;
      try{
        await api("preferences",{project,tool_mode:$("toolMode").value,minutes:$("timeout").value,plan_versions:$("roundCount").value});
        await refresh();notify(t("已保存运行设置"));
      }catch(ex){error(ex);}finally{b.disabled=false;}
    };
    $("claudeConfig").onclick=()=>claudeConfig(false);
  }
  (create?$("pName"):openRunSettings?$("timeout"):$("pPath")).focus();
  $("projectForm").onsubmit=async e=>{
    e.preventDefault();const b=e.submitter;b.disabled=true;
    try{
      const result=await api("project",{project,action:create?"add":"path",name:create?$("pName").value:"",path:$("pPath").value.trim()});
      dismiss();if(create)await navigate(result.project,null);else await refresh();
    }catch(ex){error(ex);}finally{b.disabled=false;}
  };
}
function pathCrumbs(path, sep){
  if(path===":drives")return [{label:t("磁盘"),path}];
  const parts=path.split(sep).filter(Boolean), win=sep==="\\";
  const base=win?(path.startsWith(sep+sep)?sep+sep+parts.splice(0,2).join(sep)+sep:parts.shift()+sep):"/";
  const out=[{label:base,path:base}];
  if(win)out.unshift({label:t("磁盘"),path:":drives"});
  let cur=base;
  for(const seg of parts){cur=cur+(cur.endsWith(sep)?"":sep)+seg;out.push({label:seg,path:cur});}
  return out;
}
function directoryPicker(inputId){
  const input=$(inputId), openModalVersion=modalVersion;
  input.insertAdjacentHTML("afterend",
    '<div class="path-actions">'+
      '<button type="button" class="quiet" data-dir-native>'+icon("folder")+('<span>'+t("选择目录…")+'</span></button>')+
      ('<button type="button" class="quiet" data-dir-web aria-expanded="false">'+t("在网页中浏览")+'</button>')+
    '</div>'+
    ('<section class="fb" hidden aria-label="'+t("网页目录浏览器")+'"></section>'));
  const actions=input.nextElementSibling;
  const nativeBtn=actions.querySelector("[data-dir-native]");
  const webBtn=actions.querySelector("[data-dir-web]");
  const panel=actions.nextElementSibling;
  const submit=input.form.querySelector(".dialogactions .primary");
  let pickingNative=false, browserOpen=false, opSeq=0, browseSeq=0, loadingPath=null;
  let viewMode="list", currentListing=null, fallbackNote="";

  function closeBrowser(restoreFocus){
    if(!browserOpen)return;
    browserOpen=false;
    submit.disabled=false;
    browseSeq++;
    loadingPath=null;
    panel.hidden=true;
    webBtn.setAttribute("aria-expanded","false");
    modalCancelHook=null;
    if(openModalVersion===modalVersion)$("modal").classList.remove("wide");
    if(restoreFocus && webBtn.isConnected)webBtn.focus();
  }

  function renderBrowser(opts={}){
    const listing=currentListing;
    const crumbs=listing?pathCrumbs(listing.path,listing.separator):[];
    const atRoot=!listing || !listing.parent || listing.path===listing.parent;
    const atHome=Boolean(listing?.home && listing.path===listing.home);
    const folders=listing?.drives||listing?.folders||[];
    let bodyHtml="";
    if(opts.error){
      bodyHtml='<div class="fb-error" role="alert"><p>'+esc(displayError(opts.error))+'</p><div class="fb-error-actions">'+
        (listing?('<button type="button" class="quiet" data-fb="back-listing">'+t("返回当前目录")+'</button>'):'')+
        ('<button type="button" class="quiet" data-fb="home-fallback">'+t("前往主目录")+'</button></div></div>');
    }else if(!listing){
      bodyHtml=('<div class="fb-empty" aria-live="polite"><p>'+t("正在读取目录…")+'</p></div>');
    }else if(!folders.length){
      bodyHtml='<div class="fb-empty">'+icon("folder")+('<p>'+t("此目录下没有子文件夹")+'</p><small>'+t("可直接点击「选择此目录」，或返回上一级")+'</small></div>');
    }else{
      bodyHtml='<div class="fb-items '+viewMode+('" aria-label="'+t("子文件夹列表")+'">')+folders.map(name=>
        '<button type="button" class="fb-item" data-folder="'+esc(name)+'" title="'+esc(name)+'">'+
        '<span class="fb-folder-ic" aria-hidden="true">'+icon("folder")+'</span>'+
        '<span class="fb-name">'+esc(name)+'</span>'+
        '<span class="fb-go" aria-hidden="true">'+icon("chevron")+'</span></button>').join("")+'</div>';
    }
    const crumbsHtml=crumbs.length ? crumbs.map((c,i)=>{
      const last=i===crumbs.length-1;
      return (i?'<span class="fb-sep" aria-hidden="true">/</span>':'')+
        '<button type="button" class="fb-crumb" data-fb-path="'+esc(c.path)+'"'+(last?' aria-current="location"':'')+' title="'+esc(c.path)+'">'+esc(c.label)+'</button>';
    }).join("") : ('<span class="hint">'+t("位置")+'</span>');
    panel.innerHTML=
      '<div class="fb-toolbar">'+
        '<button type="button" class="fb-navbtn" data-fb="home"'+(atHome?' aria-current="location"':'')+(' title="'+t("前往主目录")+'">')+icon("home")+(t("主目录")+'</button>')+
        '<button type="button" class="fb-navbtn" data-fb="parent"'+(atRoot?' disabled':'')+(' title="'+t("返回上一级 (Backspace)")+'">')+icon("up")+(t("上一级")+'</button>')+
        ('<div class="fb-views" role="group" aria-label="'+t("视图方式")+'">')+
          ('<button type="button" class="fb-viewbtn" data-fb-view="list" aria-label="'+t("列表视图")+'" title="'+t("列表视图")+'" aria-pressed="')+(viewMode==="list")+'">'+icon("list")+'</button>'+
          ('<button type="button" class="fb-viewbtn" data-fb-view="grid" aria-label="'+t("网格视图")+'" title="'+t("网格视图")+'" aria-pressed="')+(viewMode==="grid")+'">'+icon("grid")+'</button>'+
        '</div>'+
      '</div>'+
      (fallbackNote?'<p class="fb-note">'+esc(fallbackNote)+'</p>':'')+
      ('<nav class="fb-crumbs" aria-label="'+t("目录位置")+'">')+crumbsHtml+'</nav>'+
      '<div class="fb-body'+(opts.loading?' loading':'')+'"'+(opts.loading?' aria-busy="true"':'')+'>'+bodyHtml+'</div>'+
      '<div class="fb-footer">'+
        ('<div class="fb-selected"><span class="fb-sel-label">'+t("当前选择")+'</span><code class="fb-sel-path" title="')+esc(listing?.path||"")+'">'+esc(listing?.path||t("尚未读取"))+'</code></div>'+
        '<div class="fb-foot-actions">'+
          ('<button type="button" class="quiet" data-fb="cancel">'+t("取消")+'</button>')+
          '<button type="button" class="primary" data-fb="confirm"'+(listing?.path && !listing.drives && loadingPath===null && !opts.error?'':' disabled')+('>'+t("选择此目录")+'</button>')+
        '</div>'+
      '</div>';
    const crumbsEl=panel.querySelector(".fb-crumbs");
    if(crumbsEl)crumbsEl.scrollLeft=crumbsEl.scrollWidth;
  }

  async function loadDir(targetPath, focusBody=false){
    if(loadingPath!==null && loadingPath===targetPath)return;
    const reqId=++browseSeq;
    loadingPath=targetPath;
    if(!currentListing)renderBrowser({loading:true});
    else{
      const body=panel.querySelector(".fb-body");
      panel.querySelector('[data-fb="confirm"]').disabled=true;
      if(body){body.classList.add("loading");body.setAttribute("aria-busy","true");}
    }
    try{
      const res=await api("directories?"+new URLSearchParams({path:targetPath}));
      if(reqId===browseSeq)loadingPath=null;
      if(reqId!==browseSeq || !browserOpen || openModalVersion!==modalVersion || !panel.isConnected)return;
      currentListing={
        path:res.path||"",
        parent:res.parent||"",
        home:res.home||"",
        folders:res.folders||[], drives:res.drives, separator:res.separator||"/"
      };
      renderBrowser();
      const body=panel.querySelector(".fb-body");
      if(body){body.scrollTop=0;enter(body);}
      if(focusBody){
        const nextFocus=panel.querySelector(".fb-item") || panel.querySelector('[data-fb="confirm"]:not(:disabled)') || panel.querySelector('[data-fb="parent"]:not(:disabled)');
        nextFocus?.focus();
      }
    }catch(ex){
      if(reqId===browseSeq)loadingPath=null;
      if(reqId!==browseSeq || !browserOpen || openModalVersion!==modalVersion || !panel.isConnected)return;
      renderBrowser({error:ex?.message||t("无法读取该目录")});
      if(focusBody)panel.querySelector('[data-fb="home-fallback"]')?.focus();
    }
  }

  function openBrowser(startPath, note=""){
    opSeq++;
    fallbackNote=note;
    browserOpen=true;
    submit.disabled=true;
    currentListing=null;
    loadingPath=null;
    panel.hidden=false;
    webBtn.setAttribute("aria-expanded","true");
    $("modal").classList.add("wide");
    modalCancelHook=()=>closeBrowser(true);
    loadDir(startPath, true);
    enter(panel);
    panel.scrollIntoView({block:"nearest"});
  }

  panel.onclick=e=>{
    const btn=e.target.closest("button");
    if(!btn || btn.disabled)return;
    if(btn.dataset.fb==="home" || btn.dataset.fb==="home-fallback"){loadDir(currentListing?.home||"",true);}
    else if(btn.dataset.fb==="back-listing"){renderBrowser();}
    else if(btn.dataset.fb==="parent"){if(currentListing?.parent && currentListing.parent!==currentListing.path)loadDir(currentListing.parent,true);}
    else if(btn.dataset.fb==="confirm"){
      if(!currentListing?.path || loadingPath!==null)return;
      input.value=currentListing.path;
      closeBrowser(false);
      input.focus();
    }else if(btn.dataset.fb==="cancel"){
      closeBrowser(true);
    }else if(btn.dataset.fbView){
      viewMode=btn.dataset.fbView;
      renderBrowser();
      panel.querySelector('[data-fb-view="'+viewMode+'"]')?.focus();
    }else if(btn.dataset.fbPath!=null){
      loadDir(btn.dataset.fbPath,true);
    }else if(btn.dataset.folder!=null && currentListing){
      loadDir(currentListing.drives?btn.dataset.folder:currentListing.path+(currentListing.path.endsWith(currentListing.separator)?"":currentListing.separator)+btn.dataset.folder,true);
    }
  };

  panel.onkeydown=e=>{
    if(e.key==="Escape"){
      e.preventDefault();e.stopPropagation();closeBrowser(true);return;
    }
    if((e.key==="Backspace" && !e.target.closest("input,textarea")) || (e.altKey && e.key==="ArrowUp")){
      if(currentListing?.parent && currentListing.parent!==currentListing.path){
        e.preventDefault();loadDir(currentListing.parent,true);
      }
      return;
    }
    if(e.key==="Enter" && (e.metaKey || e.ctrlKey)){
      if(currentListing?.path && !panel.querySelector('[data-fb="confirm"]').disabled){
        e.preventDefault();input.value=currentListing.path;closeBrowser(false);input.focus();
      }
      return;
    }
    const item=e.target.closest(".fb-item");
    if(!item)return;
    const items=[...panel.querySelectorAll(".fb-item")];
    const idx=items.indexOf(item);
    if(idx<0)return;
    let next=-1;
    if(e.key==="Home")next=0;
    else if(e.key==="End")next=items.length-1;
    else if(viewMode==="list"){
      if(e.key==="ArrowDown")next=Math.min(items.length-1,idx+1);
      else if(e.key==="ArrowUp")next=Math.max(0,idx-1);
    }else{
      if(e.key==="ArrowRight")next=Math.min(items.length-1,idx+1);
      else if(e.key==="ArrowLeft")next=Math.max(0,idx-1);
      else if(e.key==="ArrowDown" || e.key==="ArrowUp"){
        const firstTop=items[0].offsetTop;
        let cols=0;while(cols<items.length && items[cols].offsetTop===firstTop)cols++;
        cols=Math.max(1,cols);
        next=e.key==="ArrowDown"?Math.min(items.length-1,idx+cols):Math.max(0,idx-cols);
      }
    }
    if(next>=0 && next!==idx){e.preventDefault();items[next].focus();}
  };

  nativeBtn.onclick=async()=>{
    if(pickingNative)return;
    pickingNative=true;
    submit.disabled=true;
    const callSeq=++opSeq;
    nativeBtn.disabled=true;
    nativeBtn.setAttribute("aria-busy","true");
    $("formError").hidden=true;
    try{
      const res=await api("choose-directory",{path:input.value.trim()});
      if(openModalVersion!==modalVersion || !panel.isConnected || callSeq!==opSeq)return;
      if(res.status==="selected" && typeof res.path==="string" && res.path){
        input.value=res.path;
        closeBrowser(false);
        input.focus();
      }else if(res.status==="unavailable"){
        openBrowser(input.value.trim(),t("本机目录选择器不可用，已切换为网页目录浏览。"));
      }
    }catch(ex){
      if(openModalVersion===modalVersion && panel.isConnected && callSeq===opSeq)error(ex);
    }finally{
      pickingNative=false;
      if(!browserOpen)submit.disabled=false;
      if(nativeBtn.isConnected){nativeBtn.disabled=false;nativeBtn.removeAttribute("aria-busy");}
    }
  };

  webBtn.onclick=()=>{
    if(browserOpen)closeBrowser(true);
    else openBrowser(input.value.trim(),"");
  };
}
async function toggleClaude(){
  if(!data)return;
  const p=project;
  if(claudePending.has(p))return;
  const currentOn=data.seats.some(s=>s.agent==="claude");
  const target=currentOn?"off":"on";
  if(!currentOn && !data.claude_configured){claudeConfig(true);return;}
  const hadModeClaude=target==="off" && $("mode").value==="claude";
  const hadFocus=document.activeElement?.id==="claudeToggle";
  const token=++claudeSeq;
  claudePending.set(p,{target,from:currentOn,token});
  if(claudeErr && claudeErr.project===p)claudeErr=null;
  render();
  let toggled=false;
  try{
    await api("claude",{project:p,enabled:target});
    toggled=true;
  }catch(ex){
    const msg=ex?.message||t("请求失败");
    const message=t(target==="on"?"项目「{project}」Claude 开启失败：{reason}":"项目「{project}」Claude 关闭失败：{reason}",{project:displayProject(p),reason:displayError(msg)});
    if(project===p)claudeErr={project:p,message};
    else notify(message);
  }
  if(toggled && project===p){
    try{await refresh();}
    catch(ex){claudeErr={project:p,message:t("状态刷新失败：{reason}",{reason:displayError(ex?.message)||t("请稍后重试")})};}
  }
  if(claudePending.get(p)?.token===token)claudePending.delete(p);
  if(data)render();
  if(toggled && hadModeClaude && project===p && !data.seats.some(s=>s.agent==="claude")){
    notify(t("项目「{project}」已关闭 Claude，讨论方式已切回「共同讨论」。",{project:displayProject(p)}));
  }
  if(hadFocus && project===p && !$("modal").open)$("claudeToggle")?.focus();
}
function claudeConfig(enable){
  const p=project;
  const version=dialog(t("Claude 出口"),('<form id="claudeForm"><label for="claudeIP">'+t("本机的公网 IPv4")+'</label>')+
    ('<input class="field" id="claudeIP" placeholder="'+t("例如 203.0.113.10")+'" inputmode="decimal" autocomplete="off" ')+(enable?'required':'')+'>'+
    ('<p class="hint">'+t("只保存在运行圆桌的电脑上。启用后会在调用期间复查。")+'</p><div class="dialogactions">')+
    (!enable && data.claude_configured?('<button class="quiet" id="clearIP" type="button">'+t("移除并关闭 Claude")+'</button>'):'')+
    '<button class="primary">'+(enable?t('核验并开启'):t('保存'))+'</button></div></form>');
  $("claudeIP").focus();
  async function save(value, button){
    button.disabled=true; $("formError").hidden=true;
    try{
      await api("claude-config",{project:p,ip:value});
      if(enable)await api("claude",{project:p,enabled:"on"});
      if(version===modalVersion)dismiss();
      await refresh();notify(enable?t("已开启 Claude"):value?t("已保存出口设置"):t("已关闭 Claude 并移除核验地址"));
    }catch(ex){if(version===modalVersion)error(ex);}
    finally{button.disabled=false;}
  }
  $("claudeForm").onsubmit=e=>{e.preventDefault(); const ip=$("claudeIP").value.trim();if(ip)save(ip,e.submitter);};
  if($("clearIP"))$("clearIP").onclick=e=>save("",e.currentTarget);
}
function showRecordFolder(id){
  const path=id?data.selected.folder:data.project_folder;
  dialog(id?t("讨论文件夹"):t("项目记录文件夹"),
    ('<p class="hint">'+t("在文件管理器中移走对应的讨论文件夹后，圆桌会更新历史。项目工作目录单独保存。")+'</p>')+
    ('<label for="recordPath">'+t("位置")+'</label><input readonly class="field" id="recordPath" value="')+esc(path)+'">'+
    ('<div class="dialogactions"><button class="quiet" id="copyPath">'+t("复制路径")+'</button>')+
    (data.native_folders?('<button class="primary" id="revealPath">'+t("在文件管理器打开")+'</button>'):'')+'</div>');
  $("copyPath").onclick=async()=>{try{await navigator.clipboard.writeText(path);notify(t("已复制路径"));}catch{$("recordPath").select();}};
  if($("revealPath"))$("revealPath").onclick=async e=>{
    const b=e.currentTarget;b.disabled=true;
    try{await api("folder",{project,session:id||""});notify(t("已打开文件夹"));}catch(ex){error(ex);}finally{b.disabled=false;}
  };
}
function resetTime(value){
  if(value==null)return t("重置时间未提供");
  const date=new Date(typeof value==="number"?value*1000:value);
  return Number.isNaN(+date)?t("重置时间未提供"):t("{time} 重置",{time:new Intl.DateTimeFormat(uiLanguage(),{month:"numeric",day:"numeric",hour:"2-digit",minute:"2-digit",hour12:false}).format(date)});
}
function formatClock(ts){
  if(ts==null)return "";
  const d=new Date(typeof ts==="number"?(ts>1e12?ts:ts*1000):ts);
  return Number.isNaN(+d)?"":d.toLocaleTimeString("zh-CN",{hour:"2-digit",minute:"2-digit",second:"2-digit",hour12:false});
}
const buckets={"gemini-5h":"Gemini · 5 小时","gemini-weekly":"Gemini · 每周","3p-5h":"Google 第三方模型池 · 5 小时","3p-weekly":"Google 第三方模型池 · 每周","gemini-argon-wtu-weekly":"Gemini Argon WTU · 每周"};
function health(){
  if(!data)return;
  const version=dialog(t("订阅额度"),'<div id="quotaList"></div>'+
    ('<p class="hint qnote">'+t("通过本机 CLI 读取账号额度，缓存 60 秒。刷新会重新查询。")+'</p>')+
    ('<div class="dialogactions"><button type="button" class="primary" id="refreshQuota" disabled>'+t("查询中…")+'</button></div>'));
  let inFlight=false;
  async function load(force){
    if(inFlight || version!==modalVersion || !data)return;
    inFlight=true;
    const reqSeq=++quotaSeq, reqProject=project, seats=data.seats.slice();
    const list=$("quotaList"), btn=$("refreshQuota");
    if(!list || !btn){inFlight=false;return;}
    $("formError").hidden=true;
    btn.disabled=true;
    btn.textContent=force?t("正在刷新…"):t("查询中…");
    list.innerHTML=seats.map(s=>'<section class="qprovider"><div class="qtitle">'+glyph(s.agent)+'<b>'+labels[s.agent]+'</b><span class="qstate busy" id="quota-status-'+s.agent+'">'+(force?t('正在刷新…'):t('正在查询…'))+'</span></div><div id="quota-'+s.agent+'" class="qbody"><p class="hint">'+(force?t('正在重新查询账号额度…'):t('正在查询账号额度…'))+'</p></div></section>').join("");
    await Promise.allSettled(seats.map(async seat=>{
      try{
        const r=await api("quota?project="+encodeURIComponent(reqProject)+"&agent="+encodeURIComponent(seat.agent)+(force?"&refresh=1":""));
        if(version!==modalVersion || reqSeq!==quotaSeq || project!==reqProject)return;
        const body=$("quota-"+seat.agent), badge=$("quota-status-"+seat.agent);
        if(!body || !badge)return;
        const isStale=Boolean(r.stale);
        const isCached=!isStale && Boolean(r.cached);
        badge.className="qstate "+(isStale?"warn":isCached?"cached":"good");
        badge.textContent=isStale?t("刷新失败"):isCached?t("已缓存"):t("额度查询成功");
        const order=w=>String(w.label||"").startsWith("gemini-5h")?0:w.label==="gemini-weekly"?1:2;
        const rows=(Array.isArray(r.windows)?r.windows:[]).slice().sort((a,b)=>order(a)-order(b));
        const rowsHtml=rows.length ? rows.map(w=>{
          const n=w.percent, title=t(buckets[w.label]||w.label);
          const empty=!w.disabled&&(typeof n==="number"?n<=0:w.amount===0);
          const low=!empty&&typeof n==="number"&&n<=10;
          return '<div class="qrow'+(empty||low?' quota-low':'')+'"><div><span>'+esc(title)+'</span><b>'+(empty?t('额度已用完'):w.disabled?t('已停用'):n==null?(w.amount==null?t('可用'):t("剩余")+' '+esc(w.amount)):t("剩余")+' '+esc(Number(n.toFixed(1)))+'%')+'</b></div>'+
            (n==null?'':'<meter min="0" max="100" value="'+esc(n)+'" aria-label="'+esc(title)+(' '+t("剩余额度")+'"></meter>'))+'<small>'+esc(resetTime(w.reset))+'</small></div>';
        }).join("") : ('<p class="hint">'+t("暂无分段额度。")+'</p>');
        const clock=formatClock(r.checked);
        const metaParts=[];
        if(r.plan)metaParts.push(esc(r.plan));
        if(clock)metaParts.push((isStale?t("上次成功读取")+" ":isCached?t("缓存于")+" ":t("查询于")+" ")+esc(clock));
        body.innerHTML=rowsHtml+(metaParts.length?'<small class="qstamp">'+metaParts.join(" · ")+'</small>':'')+
          (isStale?('<p class="formerror">'+t("显示上次查询结果"))+(r.error?'：'+esc(displayError(r.error)):'')+'</p>':'');
      }catch(ex){
        if(version!==modalVersion || reqSeq!==quotaSeq || project!==reqProject)return;
        const body=$("quota-"+seat.agent), badge=$("quota-status-"+seat.agent);
        if(!body || !badge)return;
        badge.className="qstate err";
        badge.textContent=t("查询失败");
        body.innerHTML=('<p class="formerror">'+t("账号额度查询失败"))+(ex?.message?'：'+esc(displayError(ex.message)):'')+'</p>';
      }
    }));
    inFlight=false;
    if(version===modalVersion && reqSeq===quotaSeq){
      if(project!==reqProject){load(false);return;}
      if($("refreshQuota")){
        $("refreshQuota").disabled=false;
        $("refreshQuota").textContent=t("刷新额度");
      }
    }
  }
  $("refreshQuota").onclick=()=>load(true);
  load(false);
}
async function fetchPatch(id, excerpt=false){
  const response=await fetch("/api/patch?"+new URLSearchParams({project,session:id,excerpt:excerpt?"1":"0"}),{headers:{"X-Roundtable":key}});
  if(!response.ok)throw Error((await response.json()).error);
  return response;
}
function runDialog(){
  const p=project, id=sid;
  dialog(t("按分工实施"),`<form id="runForm"><label for="runPath">${t("实施目录")}</label>
    <input class="field" id="runPath" value="${esc(data.path)}" placeholder="${t("输入已有项目目录")}" required>
    <label for="runMode">${t("实施方式")}</label><select class="field" id="runMode">
    <option value="preview">${t("先生成实施预览")}</option><option value="direct">${t("直接写入目录")}</option></select>
    <p class="hint" id="runHint"></p><div class="dialogactions"><button class="primary" id="runSubmit"></button></div></form>`);
  directoryPicker("runPath");
  const mode=$("runMode"), submit=$("runSubmit");
  function describe(){
    const preview=mode.value==="preview";
    $("runHint").textContent=t(preview?"在独立副本中实施并生成可下载的 Git 补丁，原文件保留。Git 项目须选择干净的仓库根目录。":"各席直接修改所选工作目录中的文件。");
    submit.textContent=t(preview?"生成实施预览":"开始实施");
  }
  mode.onchange=describe;describe();
  $("runForm").onsubmit=async e=>{
    e.preventDefault();const dest=$("runPath").value.trim();if(!dest)return;
    const version=modalVersion, form=e.currentTarget;
    submit.disabled=true;submit.textContent=t("正在准备目录…");
    const request=api("implement",{project:p,session:id,path:dest,mode:mode.value});
    let checking=false;
    const timer=setInterval(async()=>{
      if(checking || sid!==id || version!==modalVersion)return;
      checking=true;
      try{
        await refresh();
        if(data.selected?.id===id && data.selected.state==="implementing" && version===modalVersion)dismiss();
      }catch(ex){error(ex);}finally{checking=false;}
    },500);
    try{await request;if(version===modalVersion)dismiss();}catch(ex){error(ex);}
    finally{
      clearInterval(timer);
      if(form.isConnected){submit.disabled=false;describe();}
      await refresh().catch(error);
    }
  };
}
document.addEventListener("click",async e=>{
  const b=e.target.closest("button");if(!b)return;
  try{
    if(b.dataset.permission){
      b.dataset.busy="true"; b.disabled=true; b.textContent=t("正在提交…");
      try{await api("permission",{project,session:sid,request:b.dataset.permission,decision:b.dataset.choice});}
      finally{delete b.dataset.busy;await refresh();if(b.isConnected && data.selected){b.disabled=false;renderDiscussion(data.selected);}}
      return;
    }
    if(b.id==="jumpReply"){$("topic").focus();return;}
    if(b.id==="failureQuota"){health();return;}
    if(b.id==="failureTimeout"){projectDialog(false,true);return;}
    if(b.id==="discussionFolder"){showRecordFolder(sid);return;}
    if(b.id==="projectFolder"){showRecordFolder();return;}
    if(b.dataset.live){await navigate(b.dataset.owner,b.dataset.live);return;}
    if(b.id==="stop"){b.disabled=true;await api("stop",{project,session:sid});await refresh();return;}
    if(b.hasAttribute("data-claude-toggle")){await toggleClaude();return;}
    if(b.dataset.agent){await pickModel(b.dataset.agent);return;}
    if(b.dataset.project){const p=b.dataset.project;await api("project",{project,action:"use",name:p});await navigate(p,null);return;}
    if(b.dataset.session){await navigate(project,b.dataset.session);return;}
    if(b.id==="exportPatch"){
      const response=await fetchPatch(sid);
      const url=URL.createObjectURL(await response.blob()), link=document.createElement("a");
      link.href=url;link.download="implementation.patch";link.click();
      setTimeout(()=>URL.revokeObjectURL(url),1000);return;
    }
    if(b.id==="exportPDF"){
      const id=sid,p=project;b.disabled=true;
      try{
        if(!data.selected.has_pdf){b.textContent=t("Gemini 正在排版…");await api("pdf",{project:p,session:id});}
        const response=await fetch("/api/pdf?"+new URLSearchParams({project:p,session:id}),{headers:{"X-Roundtable":key}});
        if(!response.ok)throw Error((await response.json()).error);
        const url=URL.createObjectURL(await response.blob()), link=document.createElement("a");
        link.href=url;link.download=p+"-"+id+".pdf";link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
      }finally{await refresh();}
      return;
    }
    if(b.id==="exportRecord" || b.id==="exportPlan"){
      const id=sid, plan=b.id==="exportPlan";
      const summary=plan && closingDraft(data.selected);
      const markdown=plan ? (summary||finalDraft(data.selected)||("# "+project+" · "+t(states[data.selected.state])+"\n\n"+data.selected.plan))+"\n"
                          : (await api("record?"+new URLSearchParams({project,session:id}))).markdown;
      const url=URL.createObjectURL(new Blob([markdown],{type:"text/markdown;charset=utf-8"}));
      const link=document.createElement("a");link.href=url;link.download=(summary?t("讨论总结-"):plan?t("方案-"):t("圆桌-"))+id+".md";link.click();
      setTimeout(()=>URL.revokeObjectURL(url),1000);return;
    }
    if(b.id==="continueDispute"){
      $("mode").value="both";
      if(!$("topic").value.trim())$("topic").value=t(data.selected?.input_change?"请用目前的输入重新核对上一轮的重要结论和异议，并注明哪些判断发生变化。":"请保留上一版已同意的部分，逐条回应最后表决中的阻塞异议，并说明怎样验证修订。");
      saveDraft();$("topic").focus();return;
    }
    if(b.id==="closeDiscussion"){
      b.disabled=true;b.dataset.busy="true";b.textContent=t("正在交给 Gemini…");
      const id=sid,p=project;
      const task=api("close-discussion",{project:p,session:id});
      const timer=setTimeout(()=>{if(project===p&&sid===id)refresh().catch(error);},350);
      try{await task;}finally{
        clearTimeout(timer);delete b.dataset.busy;b.disabled=false;
        if(project===p&&sid===id){await refresh();if(b.isConnected)renderDiscussion(data.selected);}
      }
      return;
    }
    if(b.id==="resumeDiscussion"){
      b.disabled=true;const id=sid, p=project;
      const task=api("resume",{project:p,session:id});
      const timer=setTimeout(()=>{if(project===p && sid===id)refresh().catch(error);},400);
      try{await task;}finally{clearTimeout(timer);await refresh();}
      return;
    }
    if(b.id==="implement")runDialog();
  }catch(ex){error(ex);}
});
$("composer").onsubmit=async e=>{
  e.preventDefault();const topic=$("topic").value.trim();if(!topic||pending||!data||ongoing(data.selected?.state))return;
  if($("mode").value==="claude" && !data.seats.some(s=>s.agent==="claude")){
    $("mode").value="both";render();notify(t("当前项目未开启 Claude，讨论方式已切回「共同讨论」。"));return;
  }
  const p=project, parent=sid;pending=true;render();
  try{
    const next=await api("start",{project:p,session:parent||"",topic,mode:$("mode").value,moderator:$("moderator").value});
    if(project===p&&sid===parent){$("topic").value="";await navigate(p,next.session);}
  }catch(ex){error(ex);}finally{pending=false;if(data)render();}
};
$("topic").addEventListener("keydown",e=>{if(e.key==="Enter"&&(e.metaKey||e.ctrlKey)&&!e.isComposing){e.preventDefault();$("composer").requestSubmit();}});
$("new").onclick=async()=>{$("mode").value="both";await navigate(project,null);$("topic").focus();};
$("mode").onchange=()=>{if(data)render();};
$("language").onchange=e=>{
  setUiLanguage(e.target.value);
  translateShell();
  if(data){lastRenderRecord=null;render();}
};
$("reconnect").onclick=()=>refresh().catch(error);
document.addEventListener("visibilitychange",()=>{if(document.hidden)clearTimeout(poll);else refresh().catch(error);});
$("settings").onclick=()=>projectDialog(false);$("add").onclick=()=>projectDialog(true);$("health").onclick=()=>health();
$("menu").onclick=()=>{document.body.classList.add("navopen");$("closeNav").focus();};$("closeNav").onclick=closeNav;$("scrim").onclick=closeNav;
document.addEventListener("keydown",e=>{if(e.key==="Escape")closeNav();});
refresh().then(()=>{$("topic").value=readDraft();}).catch(error);
