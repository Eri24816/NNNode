from __future__ import annotations
import math
import numpy as np
from typing import Dict, List
from history import *
import datetime
import sys
import traceback
import copy
from typing import TYPE_CHECKING, TypedDict
if TYPE_CHECKING:
    import Environment
    import edge

class node_StringIO():
    def __init__(self,node):
        self.node = node
    def write(self,value):
        self.node.added_output += value

# redirect stdout
class stdoutIO():
    def __init__(self,node):
        self.node = node
    def __enter__(self):
        self.old = sys.stdout
        stdout = node_StringIO(self.node)
        sys.stdout = stdout
        return stdout
    def __exit__(self, type, value, traceback):
        sys.stdout = self.old

import ast
# exec that prints correctly
def exec_(script,globals=None, locals=None):
    stmts = list(ast.iter_child_nodes(ast.parse(script)))
    output=''
    if not stmts:
        return
    if isinstance(stmts[-1], ast.Expr):
        if len(stmts) > 1:
            ast_module = ast.parse("")
            ast_module.body=stmts[:-1]
            exec(compile(ast_module, filename="<ast>", mode="exec"), globals, locals)
        last = eval(compile(ast.Expression(body=stmts[-1].value), filename="<ast>", mode="eval"), globals, locals)
        if last:
            print(last)
    else:    
        exec(script, globals, locals)
    return output

def v3(x,y,z):
    '''
    Unity Vector3 Json format
    '''
    return {'x':x,'y':y,'z':z}


class Port():
    '''
    Different node classes might have Port classes that own different properties for frontend to read. 
    In such case, inherit this
    '''
    def __init__(self,node: Node, type : str, isInput : bool, max_connections : int = '64', name : str = '', description : str = '',pos = [0,0,0], on_edge_activate = lambda : None, with_order : bool = False):
        self.id = str(len(node.port_list))
        node.port_list.append(self)
        self.type = type
        self.isInput = isInput
        self.max_connections = max_connections
        self.name = name
        self.description = description 
        self.pos = pos
        self.on_edge_activate = on_edge_activate # A delegate
        self.flows : List[edge.ControlFlow] = [] 
        self.with_order = with_order # Whether the order of edges connected to the port matters.

    def get_dict(self):
        # for json.dump
        return {
            'id': self.id,
            'type':self.type,
            'isInput' : self.isInput,
            'max_connections' : self.max_connections,
            'with_order' : self.with_order,
            'name': self.name,
            'description' : self.description,
            'pos' : v3(*self.pos)
            }

class Attribute:
    '''
    A node can have 0, 1, or more attributes and components. 

    Attributes are states of nodes, they can be string, float or other types. Once an attribute is modified (whether in client or server),
    cilent (or server) will send "atr" command to server (or client) to update the attribute.

    Components are UI components that each controls an attribute, like slider or input field.

    Not all attributes are controlled by components, like attribute "pos". 
    '''
    def __init__(self,node : Node,name,type, value,history_in = 'node'):
        node.attributes[name]=self
        self.node = node
        self.name = name
        self.type = type # string, float, etc.
        self.value = value

        # History is for undo/redo. Every new changes of an attribute creates an history item.
        # self.history_in = '' -> no storing history
        # self.history_in = 'node' -> store history in the node, like most of the attributes
        # self.history_in = 'env' -> store history in the env, like node position
        self.history_in = history_in 
        '''
        if self.node.env:
            self.node.env.Write_update_message(self.node.id,'atr',self.name)
        '''
    
    def set(self,value, store_history:bool = True):

        # Update history
        if store_history:
            if self.history_in == 'node':
                self.node.Update_history("atr",{"id":self.node.id,"name": self.name,"old":self.value,"new":value}) 
            elif self.history_in == 'env':
                self.node.env.Update_history("atr",{"id":self.node.id,"name": self.name,"old":self.value,"new":value})

        self.value = value

        # Send to client
        self.node.env.Write_update_message(self.node.id,'atr',self.name)

    def dict(self):
        return {'name' : self.name, 'type' : self.type, 'value' : self.value, 'h' : self.history_in}
    
class Component:
    '''
    Like a slider or an input field
    A component controls an attribute.
    Componte class have no set() method. When component value is modified, client should send "atr" command, which leads to Attribute.set()
    '''
    def __init__(self,node : Node,name,type,target_attr):
        node.components.append(self)
        self.name = name # for UI to display
        self.type = type # C# class name
        self.target_attr = target_attr # attribute name
    
    def dict(self):
        return {'name':self.name,'type' : self.type, 'target_attr' : self.target_attr}

class Node:
    '''
    Base class of all types of nodes
    '''
    display_name = 'Node'
    shape : str = ''
    category = ''

    class Info(TypedDict):
        type : str
        id : int

        # for client ------------------------------
        shape : str     # CodeNode, FunctionNode, RoundNode
        category : str
        doc : str
        name : str              # Just for frontend. In backend we never use it but use "id" instead
        output : str            # Output is necessary for all classes of node to at least store exceptions occured in nodes
        portInfos : List[Dict]  # PortInfos are determined by server side Node classes and is used to tell client how to set up ports

    @classmethod
    def get_class_info(cls)->Info:
        '''
        When creating demo node, this is sent to client
        '''
        tempNode = cls({'id' : -1, 'name' : ''},env = None)
        return tempNode.get_info()
    
    def get_info(self) -> Dict[str]:
        '''
        Node info
        History item "new" stores this. When creating new node, this is sent to all clients.
        And when client sends redo, the node can be recreated from it. 
        '''
        return {
            "type":type(self).__name__,"id":self.id,"category" : self.category,"doc":self.__doc__,"name":self.display_name,"output":self.output,'shape' : self.shape,
        'portInfos' : [port.get_dict() for port in self.port_list],
        'attr': [attr.dict()for _, attr in self.attributes.items()],
        'comp': [comp.dict()for  comp in self.components]
        }
    

    def __init__(self, info : Info, env : Environment.Env):
        '''
        For child classes, DO NOT override this. Override initialize() instead.
        '''
        # The environment
        self.env=env

        # For the API, each ports of the node are identified by position in this list
        # Create ports in __init__ then add all port into this list
        self.port_list : List[Port] = []

        # Each types of node have different attributes. Client can set them by sending "atr" command.
        # Changes of attributes will create update messages and send to clients with "atr" command.
        self.attributes : Dict[str,Attribute] = {}
        self.components : List[Attribute] = []

        self.type=type(self).__name__
        self.id=info['id']

        # Is the node ready to run?
        self.active = False

        self.output = info['output'] if 'output' in info else ''

        # added lines of output when running, which will be sent to client
        self.added_output = "" 

        if self.id != -1:
            self.first_history = self.latest_history = History_item("stt")
            self.lock_history=False

        self.initialize() 

        if self.id != -1:
            self.env.Update_history("new", self.get_info())

        #Attribute(self,'pos','Vector3',v3(0,0,0))
        
        if 'attr' in info:
            for attr_dict in info['attr']:
                if attr_dict['name'] in self.attributes:
                    self.attributes[attr_dict['name']].set(attr_dict['value'])
                else:
                    # Some attributes could be created by client. self.initialize() doesn't add them to self.attributes.
                    Attribute(self,attr_dict['name'],attr_dict['type'],attr_dict['value'],attr_dict['h']).set(attr_dict['value'])

    def initialize(self):
        '''
        Setup the node's attributes and components
        This method is separated from __init__() because overrides of initialize() should be called after some setup in __init__()
        '''

        pass

    def activate(self):
        if self.active: 
            return # prevent duplication in env.nodes_to_run
        self.active = True
        self.env.nodes_to_run.put(self)
        
        # for client ------------------------------
        self.env.Write_update_message(self.id, 'act', '1')  # 1 means "pending" (just for client to display)

    def deactivate(self):
        self.active = False

        # for client ------------------------------
        self.env.Write_update_message(self.id, 'act', '0')

    def flush_output(self): # called when client send 'upd'
        if self.added_output == '':
            return
        self.output += self.added_output
        self.env.Write_update_message(self.id, 'out', self.added_output) # send client only currently added lines of output
        self.added_output = ''

    def run(self):
        # Env calls this method
        self.env.Write_update_message(self.id,'act','2') # 2 means "running"
        self.env.Write_update_message(self.id, 'clr') # Clear output

        # Redirect printed outputs and error messages to client
        with stdoutIO(self):
            try:
                self._run()
            except Exception:
                self.running_finished(False)
                self.added_output += traceback.format_exc()
                self.flush_output()
            else:
                self.running_finished(True)

        

    def _run(self):
        # Actually define what the type of node acts
        pass
    
    def running_finished(self,success = True):
        pass

    # for client ------------------------------
    def recive_command(self,m):
        '''
        {'id',command' : 'act'}
        {'id',command' : 'atr', 'name', 'value'}
        '''
        command = m['command']
        if command == "act":
            self.activate()
        if command =='atr':
            self.attributes[m['name']].set(m['value'])
            
        if command == 'nat':
            if m['name'] not in self.attributes:
                Attribute(self,m['name'],m['type'],None,m['h']).set(m['value'],False) # Set initial value
            
    

    def Update_history(self, type, content):
        '''
        type, content:
        stt, None - create the node
        atr, {name, old, new} - change attribute
        '''
        if self.lock_history:
            return
        # don't repeat atr history within 3 seconds 
        if type=="atr" and self.latest_history.type=="atr" and content['id'] == self.latest_history.content['id']:
            if (datetime.datetime.now() - self.latest_history.time).seconds<3:
                self.latest_history.content['new']=content['new']
                self.latest_history.version+=1
                return

        # add an item to the linked list
        self.latest_history=History_item(type,content,self.latest_history) 
        #print(traceback.print_stack())
        print(self.first_history)
        

    def Undo(self):
        if self.latest_history.last==None:
            return 0 # nothing to undo

        if self.latest_history.type=="atr":
            self.attributes[self.latest_history.content['name']].set(self.latest_history.content['old'])
        
        self.latest_history.head_direction=-1
        self.latest_history=self.latest_history.last
        self.latest_history.head_direction = 0

        print(self.first_history)

        return 1
    
    def Redo(self):
        if self.latest_history.next==None:
            return 0 # nothing to redo
        self.latest_history.head_direction=1
        self.latest_history=self.latest_history.next
        self.latest_history.head_direction=0

        if self.latest_history.type=="atr":
            self.attributes[self.latest_history.content['name']].set(self.latest_history.content['new'])
        print(self.first_history)

        return 1

    def remove(self):
        for port in self.port_list:
            for flow in copy.copy(port.flows):
                flow.remove()
        self.env.nodes.pop(self.id)
        self.env.Update_history("rmv",self.get_info())
        del self  #*?    

class CodeNode(Node):
    '''
    A node with editable code, like a block in jupyter notebook.

    The node will be invoked when its input Controlflow is activated or double click on the node.
    It will execute its code and activate its output ControlFlow (if there is one).
    '''

    shape = 'Simple'
    category = 'basic'
    display_name = 'Code'

    def initialize(self):
        super().initialize()

        self.in_control = Port(self,'ControlPort', True, on_edge_activate = self.in_control_activate, pos = [-1,0,0])
        self.out_control = Port(self,'ControlPort', False, pos = [1,0,0])

        self.code = Attribute(self,'code','string','')
        Component(self,'input_field','TextEditor','code')
       
    def in_control_activate(self):
        # The node is activated as soon as its input flow is activated
        self.activate()

    def _run(self):
        for flow in self.in_control.flows:
            flow.deactivate()

        exec_(self.code.value,self.env.globals,self.env.locals)

    def running_finished(self, success = True):
        self.flush_output()
        if success:
            for flow in self.out_control.flows:
                flow.activate()
        self.deactivate()

class EvalAssignNode(Node):

    shape = 'Simple'
    category = 'basic'
    display_name = 'Evaluate or Assign'

    def initialize(self):
        super().initialize()
        
        self.in_data = Port(self,'DataPort',True,64,pos = [-1,0,0], on_edge_activate = self.in_data_active)
        self.out_data = Port(self,'DataPort',False,64,pos = [1,0,0])

        self.code = Attribute(self,'code','string','')
        Component(self,'input_field','SmallTextEditor','code')

    def in_data_active(self):
        #TODO : Check if in data is empty and ask for value
        self.activate()
        

    def _run(self):
        if len(self.in_data.flows)>0:
            for flow in self.in_data.flows:
                flow.deactivate()

            if len(self.in_data.flows) == 1:
                self.value = self.in_data.flows[0].data
            else:
                self.value = []
                for flow in self.in_data.flows:
                    self.value.append(flow.data)
            #exec_(self.attributes['code'] + " = __value", self.env.globals, {'__value' : self.value})
            self.env.globals.update({self.code.value: self.value})
        else:
            self.value = eval(self.code.value,self.env.globals,self.env.locals)
        

    def running_finished(self, success = True):
        if success:
            self.flush_output()
            for flow in self.out_data.flows:
                flow.recive_value(self.value)
        self.deactivate()
        
class FunctionNode(Node):
    '''
    Similar to CodeNode, but a FunctionNode's code defines a function (start with "def").
    The function is invoked when every input dataflows and the input controlflow (if there is one) are all activated.
    It can also be invoked directly by client(e.g. double click on the node).
    After running, it will activate its output dataflows and ControlFlow (if there is one).
    '''

    display_name = 'Function'
    category = 'function'

    class Info(Node.Info):
        in_names : List[str]
        out_names : List[str]
        allow_multiple_in_data : List[bool]

    # Most of the child classes of FunctionNode just differ in following 4 class properties and their function() method.
    shape = 'General'
    in_names : List[str] = []
    out_names : List[str] = []
    max_in_data : List[int] = []

    def initialize(self):
        '''
        info: {type=FunctionNode,id,name,pos,output}
        '''
        super().initialize()

        if self.shape == 'Round':
            in_port_pos = [[math.cos(t),math.sin(t),0.0] for t in np.linspace(np.pi/2,np.pi*3/2,len(self.in_names)+2)[1:-1]]
            out_port_pos = [[math.cos(t),math.sin(t),0.0] for t in np.linspace(np.pi/2,-np.pi/2,len(self.out_names)+2)[1:-1]]
        else :
            in_port_pos = [[0,0,0]]*len(self.in_names)
            out_port_pos = [[0,0,0]]*len(self.out_names)
        
        if self.max_in_data == []:
            self.max_in_data = [1]*len(self.in_names)

        # Initialize ports from self.in_names, self.out_names and self.max_in_data
        self.in_data = [Port(self,'DataPort',True,name = port_name,max_connections= max_in_data,
         on_edge_activate = self.in_data_activate, pos= pos)for (port_name,max_in_data,pos) in zip(self.in_names,self.max_in_data,in_port_pos)]
        self.out_data = [Port(self,'DataPort',False,name = port_name, pos = pos)for port_name,pos in zip(self.out_names,out_port_pos)]

    def in_data_activate(self):
        # A functionNode activates when all its input dataFlow is active.
        for port in self.in_data:
            for flow in port.flows:
                if not flow.active:
                    return
        self.activate()

    def activate(self):
        super().activate()

        # TODO: Ask for value
        # Or should it be put in _run() ?
        for port in self.in_data:
            for flow in port.flows:
                if not flow.has_value:
                    pass


    def _run(self):
        for port in self.in_data:
            for flow in port.flows:
                flow.deactivate()

        # Gather data from input dataFlows
        funcion_input = []
        for port,max_in_data in zip(self.in_data,self.max_in_data):
            if max_in_data == 1:
                if len(port.flows) == 0:
                    funcion_input.append(None) #TODO: Default value
                else:
                    funcion_input.append(port.flows[0].data)
            else:
                # Gather inpute data into a list
                funcion_input.append([flow.data for flow in port.flows])
        
        # Evaluate the function
        result = self.function(*funcion_input)

        # Send data to output dataFlows
        if len(self.out_data) == 1:
            for flow in self.out_data[0].flows:
                flow.recive_value(result)

        # if result is tuple
        elif len(self.out_data) > 1:
            i=0
            for result_item in result:
                for flow in self.out_data[i].flows:
                    flow.recive_value(result_item)
                i+=1

    def running_finished(self, success = True):
        self.deactivate()

    @staticmethod
    def function():
        # Inherit FunctionNode to write different function.
        # If one input port has more than one dataFlows connected, their data will input to this function as a list.
        pass

