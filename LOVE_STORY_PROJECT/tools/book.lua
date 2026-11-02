-- Pandoc-фильтр книги: превращает смысловые блоки рукописи
-- (.chapter, .photo, .pair, .bleed, .quotepage …) в вёрстку под формат.
-- Переменные окружения:
--   BOOK_TARGET = print | mobile | epub | docx
--   ART_EXT     = svg | png

local target = os.getenv("BOOK_TARGET") or "print"
local art_ext = os.getenv("ART_EXT") or "png"
local is_html = (target == "print" or target == "mobile")
local is_docx = (target == "docx")
local is_epub = (target == "epub")

local function pagebreak()
  if is_docx then
    return pandoc.RawBlock("openxml", '<w:p><w:r><w:br w:type="page"/></w:r></w:p>')
  end
  return pandoc.Div({})
end

local function styled(style, blocks)
  -- в DOCX — абзацный стиль, в HTML/EPUB — класс
  if is_docx then
    return pandoc.Div(blocks, pandoc.Attr("", {}, {["custom-style"] = style}))
  end
  return pandoc.Div(blocks, pandoc.Attr("", {style:lower():gsub(" ", "-")}))
end

local function photo_src(slot)
  return (os.getenv("PHOTO_DIR") or "photos") .. "/photo-" .. slot .. ".jpg"
end

local function image(src, cls, alt)
  local attr = pandoc.Attr("", cls and {cls} or {})
  return pandoc.Image(alt or {}, src, "", attr)
end

-- абзац, состоящий из одного Span с классом → отдельный стиль абзаца (для DOCX)
local span_styles = {
  source = "Quote Source", year = "Poem Year", ["final-sub"] = "Final Sub",
  ["cover-title"] = "Cover Title", ["cover-sub"] = "Cover Sub", ["cover-author"] = "Cover Author",
  ["tp-author"] = "Title Author", ["tp-title1"] = "Title Main", ["tp-title2"] = "Title Main",
  ["tp-sub"] = "Title Sub", ["tp-place"] = "Title Place",
}

function Para(el)
  if #el.content == 1 and el.content[1].t == "Span" then
    local sp = el.content[1]
    for _, c in ipairs(sp.classes) do
      if span_styles[c] then
        if is_docx then
          return pandoc.Div({pandoc.Para(sp.content)},
            pandoc.Attr("", {}, {["custom-style"] = span_styles[c]}))
        else
          return pandoc.Div({pandoc.Para(sp.content)}, pandoc.Attr("", {c}))
        end
      end
    end
  end
end

local function caption_blocks(div)
  return div.content
end

local function photo_block(div)
  local slot = div.attributes["slot"]
  local orient = div.attributes["orient"] or "portrait"
  if is_html then
    return pandoc.Div({
      pandoc.Div({pandoc.Para({image(photo_src(slot), "ph-" .. orient)})}, pandoc.Attr("", {"frame", orient})),
      pandoc.Div(caption_blocks(div), pandoc.Attr("", {"caption"})),
    }, pandoc.Attr("", {"photo-page"}, {["data-slot"] = slot}))
  end
  local out = {pagebreak()}
  table.insert(out, styled("Photo", {pandoc.Para({image(photo_src(slot))})}))
  table.insert(out, styled("Caption", caption_blocks(div)))
  table.insert(out, pagebreak())
  return out
end

local function pair_block(div)
  local slots = {}
  for s in string.gmatch(div.attributes["slots"] or "", "[^,]+") do table.insert(slots, s) end
  if is_html then
    local imgs = {}
    for _, s in ipairs(slots) do
      table.insert(imgs, pandoc.Div({pandoc.Para({image(photo_src(s))})}, pandoc.Attr("", {"pair-cell"})))
    end
    return pandoc.Div({
      pandoc.Div(imgs, pandoc.Attr("", {"pair-row"})),
      pandoc.Div(caption_blocks(div), pandoc.Attr("", {"caption"})),
    }, pandoc.Attr("", {"photo-page", "pair"}))
  end
  local inl = {}
  for i, s in ipairs(slots) do
    if i > 1 then table.insert(inl, pandoc.Space()) end
    local img = image(photo_src(s))
    if is_docx then img.attributes["width"] = "45%" end
    table.insert(inl, img)
  end
  return {pagebreak(), styled("Photo", {pandoc.Para(inl)}), styled("Caption", caption_blocks(div)), pagebreak()}
end

local function bleed_block(div)
  local slot = div.attributes["slot"]
  if target == "print" then
    return pandoc.Div({
      pandoc.Para({image(photo_src(slot), "bleed-img")}),
      pandoc.Div(caption_blocks(div), pandoc.Attr("", {"bleed-caption"})),
    }, pandoc.Attr("", {"bleed-page"}, {["data-slot"] = slot}))
  end
  div.attributes["orient"] = "full"
  return photo_block(div)
end

local function quote_page(div)
  if is_docx then
    local inner = {}
    for _, b in ipairs(div.content) do
      if b.t == "Div" then table.insert(inner, b)       -- источник (уже стилизован)
      else table.insert(inner, styled("Quote Page", {b})) end
    end
    local out = {pagebreak()}
    for _, b in ipairs(inner) do table.insert(out, b) end
    table.insert(out, pagebreak())
    return out
  end
  return div
end

local simple_docx = {
  dedication = "Dedication", epigraph = "Epigraph", letter = "Letter", messages = "Messages",
  notes = "Notes", songnote = "Song Note", chronology = "Chronology", note = "Small Note",
  ["anthology-intro"] = "Small Note", poem = "Poem", sayings = "Sayings", final = "Final",
  colophon = "Colophon", imprint = "Imprint", halftitle = "Half Title",
}

local breaks_before = {halftitle = true, titlepage = true, imprint = true, dedication = true,
  epigraph = true, contents = true, final = true, colophon = true}

function Div(div)
  local c = div.classes
  if c:includes("photo") then return photo_block(div) end
  if c:includes("pair") then return pair_block(div) end
  if c:includes("bleed") then return bleed_block(div) end
  if c:includes("quotepage") then return quote_page(div) end

  if c:includes("cover") then
    if is_epub then return {} end
    if is_docx then
      return {styled("Photo", {pandoc.Para({image("art/cover.png")})}), pagebreak()}
    end
    return pandoc.Div({pandoc.Para({image("art/cover-art." .. art_ext, "cover-img")}),
      pandoc.Div(div.content, pandoc.Attr("", {"cover-text"}))}, pandoc.Attr("", {"cover"}))
  end
  if (c:includes("halftitle") or c:includes("contents")) and is_epub then return {} end

  if is_docx then
    for cls, style in pairs(simple_docx) do
      if c:includes(cls) then
        local out = {}
        if breaks_before[cls] then table.insert(out, pagebreak()) end
        -- вложенные стилизованные Div (например, источник цитаты) не перекрашиваем
        local plain, inner = {}, {}
        for _, b in ipairs(div.content) do
          if b.t == "Div" and b.attributes["custom-style"] then
            if #plain > 0 then table.insert(out, styled(style, plain)); plain = {} end
            table.insert(out, b)
          else
            table.insert(plain, b)
          end
        end
        if #plain > 0 then table.insert(out, styled(style, plain)) end
        return out
      end
    end
    if c:includes("titlepage") or c:includes("contents") then
      table.insert(div.content, 1, pagebreak())
      return div.content
    end
  end
  return div
end

-- Главы
local function chapter_header(h)
  local label = h.attributes["label"] or ""
  local plate = h.attributes["plate"]
  local fig = h.attributes["fig"] or ""
  local title = h.content

  if is_html then
    local opener = {}
    if plate then
      table.insert(opener, pandoc.Div({pandoc.Para({image("art/" .. plate .. "." .. art_ext, "plate-img")})},
        pandoc.Attr("", {"plate"})))
      table.insert(opener, pandoc.Div({pandoc.Para({pandoc.Str(fig)})}, pandoc.Attr("", {"fig"})))
    end
    table.insert(opener, pandoc.Div({pandoc.Para({pandoc.Str(label)})}, pandoc.Attr("", {"label"})))
    table.insert(opener, pandoc.Header(1, title, pandoc.Attr("", {"chapter-title"})))
    local cls = {"chapter-opener"}
    if h.classes:includes("backmatter") then cls = {"chapter-opener", "back-opener"} end
    return pandoc.Div(opener, pandoc.Attr(h.identifier, cls))
  end

  local text = {pandoc.Str(label), pandoc.Str("."), pandoc.Space()}
  for _, i in ipairs(title) do table.insert(text, i) end
  local out = {pandoc.Header(1, text, pandoc.Attr(h.identifier, {}))}
  if plate then
    local img = image("art/" .. plate .. ".png")
    if is_docx then img.attributes["width"] = "60%" end
    table.insert(out, styled("Plate", {pandoc.Para({img})}))
  end
  return out
end

function Header(h)
  if h.level == 1 and (h.classes:includes("chapter") or h.classes:includes("backmatter")) then
    return chapter_header(h)
  end
  if h.level == 2 and h.classes:includes("poet") and is_html then
    h.classes:insert("poet")
  end
  return h
end

function Meta(m)
  -- в DOCX титул и так есть в тексте; убираем автоматический блок Pandoc
  if is_docx then m.title = nil; m.subtitle = nil; m.author = nil end
  return m
end

return {
  {Meta = Meta},
  {Para = Para},
  {Div = Div, Header = Header},
}
