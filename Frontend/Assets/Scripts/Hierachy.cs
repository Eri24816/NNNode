using System.Collections;
using System.Collections.Generic;
using UnityEngine;

public class Hierachy : MonoBehaviour
{

    [SerializeField]
    RectTransform rootPanel;

    public void AddItem(string categoryString, string containerPrefabName)
    {

    }

    public Transform FindCategoryPanel(string categoryString, string containerPrefabName)
    {
        string[] cat = categoryString.Split('/');
        Transform panel = rootPanel;
        foreach (string n in cat)
        {
            var t = panel.Find(n);
            if (t) panel = t;
            else
            {
                GameObject c = Theme.ins.Create(containerPrefabName);
                c.transform.SetParent(panel);
                panel = c.transform;
                panel.SetSiblingIndex(panel.parent.childCount - 2);
                panel.GetComponentInChildren<TMPro.TMP_Text>().text = n;
                panel.name = n;
            }
        }
        if (cat.Length == 1)
            panel.GetComponent<UnityEngine.UI.VerticalLayoutGroup>().padding.left = 5;
        return panel.Find("NodePanel");
    }
    public void Clear()
    {
        foreach (Transform child in rootPanel)
        {
            child.name = "";
            Destroy(child.gameObject);
        }
    }

    bool collapsed = false;
    public void CollapseButtonPressed()
    {
        collapsed ^= true;
        if (collapsed) ((RectTransform)transform).sizeDelta = new Vector2(0, ((RectTransform)transform).sizeDelta.y);
        else ((RectTransform)transform).sizeDelta = new Vector2(250, ((RectTransform)transform).sizeDelta.y);
    }
}