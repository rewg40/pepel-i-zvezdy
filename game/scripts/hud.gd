extends CanvasLayer
## Прицел, подсказки и панель состояния зомби (тело / конечности).

var main: Node
var labels := {}
var info: Label
var crosshair: Control


func setup(main_node: Node) -> void:
	main = main_node
	var root := Control.new()
	root.set_anchors_preset(Control.PRESET_FULL_RECT)
	root.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(root)

	crosshair = ColorRect.new()
	crosshair.color = Color(1, 1, 1, 0.75)
	crosshair.size = Vector2(3, 3)
	crosshair.set_anchors_preset(Control.PRESET_CENTER)
	crosshair.position = Vector2(-1.5, -1.5)
	crosshair.mouse_filter = Control.MOUSE_FILTER_IGNORE
	root.add_child(crosshair)

	info = Label.new()
	info.position = Vector2(24, 20)
	info.add_theme_font_size_override("font_size", 15)
	info.text = "ЛКМ — удар мечом (3 удара по конечности её отрубают)\n" \
		+ "WASD — ходьба, Shift — бег, мышь — камера, Esc — курсор\n" \
		+ "У зомби тело 1000 HP, руки и ноги по 3 HP."
	root.add_child(info)

	var panel := VBoxContainer.new()
	panel.position = Vector2(24, 96)
	panel.add_theme_constant_override("separation", 6)
	root.add_child(panel)
	for z in main.zombies:
		var l := Label.new()
		l.add_theme_font_size_override("font_size", 14)
		panel.add_child(l)
		labels[z] = l


func _process(_delta: float) -> void:
	for z in labels.keys():
		var l: Label = labels[z]
		if not is_instance_valid(z):
			continue
		if z.dead:
			l.text = "%s — мёртв" % z.title
			continue
		var legs := int(z.alive["leg_l"]) + int(z.alive["leg_r"])
		var arms := int(z.alive["arm_l"]) + int(z.alive["arm_r"])
		var mode: String = {"walk": "идёт", "limp": "хромает",
			"crawl": "ползёт"}.get(z.state, z.state)
		l.text = "%s  тело %.0f/%.0f  руки %d/2  ноги %d/2  (%s)" % [
			z.title, z.hp, z.max_hp, arms, legs, mode]
