using System.Collections;
using System.Collections.Generic;
using UnityEngine;
namespace GraphUI
{
    public class SimpleNode : Node
    {
        protected override void CreatePort(Newtonsoft.Json.Linq.JToken portInfo)
        {
            GameObject prefab;
            if ((string)portInfo["type"] == "ControlPort")
                prefab = (bool)portInfo["isInput"] ? Manager.ins.inControlPortPrefab : Manager.ins.outControlPortPrefab;
            else
                prefab = (bool)portInfo["isInput"] ? Manager.ins.inDataPortPrefab : Manager.ins.outDataPortPrefab;

            Port newPort = Instantiate(prefab,transform).GetComponent<Port>();
            ports.Add(newPort);
            newPort.Init(this, portInfo);
            

            
        }
        public override void SetupPort(Port port, Newtonsoft.Json.Linq.JToken portInfo)
        {
            port.GetComponent<UnityEngine.UI.LayoutElement>().ignoreLayout = true;
            var t = ((RectTransform)port.transform);
            if ((bool)portInfo["isInput"])
            {
                
                t.anchoredPosition = new Vector2(-1,0);
                t.anchorMin = new Vector2(0,0.5f);
                t.anchorMax = new Vector2(0, 0.5f);
            }
            else
            {
                t.anchoredPosition = new Vector2(1, 0);
                t.anchorMin = new Vector2(1, 0.5f);
                t.anchorMax = new Vector2(1, 0.5f);
            }
            port.minDir = port.maxDir = (bool)portInfo["isInput"] ? Mathf.PI : 0;
            if ((bool)portInfo["isInput"]) port.transform.SetAsFirstSibling();
            else port.transform.SetAsLastSibling();
            port.DisplayKnob();
        }
    }
}