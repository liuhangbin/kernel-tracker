function tree_link_click(obj, input_name, name)
{
	switcher = obj.parentNode.parentNode
	switcher.querySelector('.tree_switcher_label').innerHTML = obj.innerHTML;
	switcher.querySelector('[name=' + input_name + ']').setAttribute('value', name);
}
