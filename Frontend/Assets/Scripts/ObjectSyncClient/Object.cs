﻿using Newtonsoft.Json.Linq;
using System.Collections.Generic;

namespace ObjectSync
{
    public class Object
    {
        public string Id { get; private set; }
        public string Type { get; private set; }
        public Dictionary<string, Attribute> attributes { get; private set; }
        Object()
        {
        }
        public Attribute RegisterAttr(string name, string type, Attribute.SetDel setDel = null, Attribute.GetDel getDel = null, object initValue = null, string history_in = "node")
        {
            if (attributes.ContainsKey(name))
            {
                Attribute attr = attributes[name];
                if (setDel != null)
                {
                    attr.setDel.Add(setDel);
                    setDel(attr.Get());
                }
                if (getDel != null)
                    attr.getDel = getDel;

                return attr;
            }
            else
            {
                void SendNat<T>() => Space.ins.SendToServer(new Attribute.API_nat<T> { command = "new attribute", id = Id, name = name, type = type, h = history_in, value = initValue == null ? default(T) : (T)initValue });
                switch (type)
                {
                    case "string":
                        SendNat<string>(); break;
                    case "float":
                        SendNat<float>(); break;
                    case "Vector3":
                        SendNat<UnityEngine.Vector3>(); break;
                    case "bool":
                        SendNat<bool>(); break;
                }

                Attribute a = new Attribute(Id ,name, type, setDel, getDel);
                a.Set(initValue, false);
                return a;
            }
        }

        public virtual void Init(JToken d)
        {
            /*
             * Parse the node info to setup the node.
            */

            Id = (string)d["id"];

            attributes = new Dictionary<string, Attribute>();
           
            if (createByThisClient)
                Space.ins.SendToServer(new API_new(this));
            else
                // If createByThisClient, set Pos attribute after the node is dropped to its initial position (in OnDragCreating()).
                Pos = Attribute.Register(this, "transform/pos", "Vector3", (v) => { transform.position = (Vector3)v; }, () => { return transform.position; }, history_in: "env");
            Output = Attribute.Register(this, "output", "string", (v) => { OnOutputChanged((string)v); }, history_in: "", initValue: "");

            foreach (var attr_info in d["attr"])
            {
                var new_attr = new Attribute(this, (string)attr_info["name"], (string)attr_info["type"], null, null, null);
                new_attr.Set(JsonHelper.JToken2type(attr_info["value"], new_attr.type), false);
            }

            foreach (var comp_info in d["comp"])
            {
                Comp newComp;
                string type = (string)comp_info["type"];
                if (type.Length >= 8 && type.Substring(0, 8) == "Dropdown")
                    newComp = Instantiate(Space.ins.compPrefabDict["Dropdown"], componentPanel).GetComponent<Comp>();
                else
                    newComp = Instantiate(Space.ins.compPrefabDict[type], componentPanel).GetComponent<Comp>();
                if (!isDemo)
                    newComp.InitWithInfo(this, comp_info);
                comps.Add(newComp);
            }

            Attribute.Register(this, "color", "Vector3", (v) => { var w = (Vector3)v; SetColor(new Color(w.x, w.y, w.z)); }, history_in: "");


            foreach (var portInfo in d["portInfos"])
            {
                CreatePort(portInfo);
            }
        }
    }
}