// gen.mjs - 蓝图数据文档生成管线
// 输入：用户提示词 + 可选 LLM 配置；输出：blueprint 项目文档对象（sections）
// 模式：
//   1) 已配置 LLM → 调用大模型生成 JSON 文档（国内外皆可）
//   2) 未配置 → 内置确定性演示生成器（本地免 Key 跑通）
import { callLLM, extractJson } from "./llm.mjs";

// ---------- 文档字段说明（与 bundle 消费端一致） ----------
// projectName, projectDescription, originalPrompt, nodes[], wiring[], electricalConnections[],
// parts[], mechanical[], mechanicalConnections[], assembly[], instructionSteps[], instructionPreamble,
// notes[], userImages[], renderPosition, visualSnaps[]

// ---------- 演示模板（确定性，含 6 套常见场景 + 通用兜底） ----------
const demoTemplates = [
  {
    match: [/机器臂|机械臂|robotic|robot arm|arm/i],
    build(prompt) {
      return {
        projectName: "六自由度机械臂",
        projectDescription: "由 ESP32 控制的六自由度机械臂，可抓取和移动小物体，支持上位机控制与自动往复演示。",
        nodes: [
          { id: "n1", name: "ESP32 开发板", category: "Microcontroller", type: "ESP32 DevKit V1", pins: "GPIO", dimensions: "55 x 28 x 15 mm", material: "PCB", printSettings: null },
          { id: "n2", name: "SG90 舵机 x6", category: "Actuator", type: "SG90 Servo", pins: "PWM", dimensions: "23 x 12 x 22 mm", material: "塑料/金属齿轮", printSettings: null },
          { id: "n3", name: "PCA9685 舵机驱动板", category: "Driver", type: "PCA9685", pins: "I2C", dimensions: "62 x 42 x 12 mm", material: "PCB", printSettings: null },
          { id: "n4", name: "5V 电源模块", category: "Power", type: "MP1584 Buck", pins: "VIN/VOUT", dimensions: "22 x 17 x 5 mm", material: "PCB", printSettings: null },
          { id: "n5", name: "12V 电源适配器", category: "Power", type: "12V 2A Adapter", pins: "DC", dimensions: "80 x 45 x 35 mm", material: "外壳 ABS", printSettings: null },
          { id: "n6", name: "机械臂基座（打印件）", category: "Structure", type: "3D Printed Base", pins: null, dimensions: "120 x 120 x 60 mm", material: "PLA", printSettings: "层高 0.2mm，填充 40%" }
        ],
        wiring: [
          { source: "n1", target: "n3", sourcePin: "SDA/SCL", targetPin: "SDA/SCL", protocol: "I2C", voltage: "3.3V" },
          { source: "n1", target: "n3", sourcePin: "5V/GND", targetPin: "VCC/GND", protocol: "Power", voltage: "5V" },
          { source: "n3", target: "n2", sourcePin: "CH0-CH5", targetPin: "PWM", protocol: "PWM", voltage: "5V" },
          { source: "n4", target: "n3", sourcePin: "OUT", targetPin: "VIN", protocol: "Power", voltage: "5V" },
          { source: "n5", target: "n4", sourcePin: "DC", targetPin: "IN", protocol: "Power", voltage: "12V" }
        ],
        electricalConnections: [
          { source: "ESP32 开发板", target: "PCA9685 舵机驱动板", type: "I2C 通信", protocol: "I2C", voltage: "3.3V" },
          { source: "PCA9685 舵机驱动板", target: "SG90 舵机 x6", type: "PWM 控制", protocol: "PWM", voltage: "5V" },
          { source: "12V 电源适配器", target: "5V 电源模块", type: "供电", protocol: "DC", voltage: "12V" },
          { source: "5V 电源模块", target: "PCA9685 舵机驱动板", type: "供电", protocol: "DC", voltage: "5V" }
        ],
        parts: [
          { partType: "mcu", name: "ESP32 开发板", type: "Microcontroller", category: "控制核心", qty: 1, price: 28, description: "Wi-Fi/蓝牙双模主控，运行固件并驱动 PCA9685。" },
          { partType: "motor", name: "SG90 舵机", type: "Servo", category: "执行器", qty: 6, price: 9, description: "180° 微型舵机，用于六个关节的转动。" },
          { partType: "misc", name: "PCA9685 舵机驱动板", type: "Driver", category: "驱动", qty: 1, price: 12, description: "I2C 接口 16 通道 PWM 驱动板。" },
          { partType: "power", name: "MP1584 降压模块", type: "Buck Converter", category: "电源", qty: 1, price: 5, description: "12V 转 5V 降压，为舵机供电。" },
          { partType: "power", name: "12V 2A 电源适配器", type: "Adapter", category: "电源", qty: 1, price: 20, description: "交流市电转 12V 直流。" },
          { partType: "structural", name: "机械臂结构件（打印）", type: "3D Print", category: "结构", qty: 1, price: 15, description: "基座、连杆、夹具的 3D 打印件（PLA）。" },
          { partType: "connector", name: "杜邦线/螺丝套件", type: "Connector", category: "连接", qty: 1, price: 8, description: "公母杜邦线、M3 螺丝螺母若干。" }
        ],
        mechanical: [
          { id: "m1", name: "基座", type: "Base", material: "PLA", joint: "固定" },
          { id: "m2", name: "腰关节", type: "Rotation", material: "PLA+舵机", joint: "SG90 直驱" },
          { id: "m3", name: "肩关节", type: "Rotation", material: "PLA+舵机", joint: "SG90 直驱" },
          { id: "m4", name: "肘关节", type: "Rotation", material: "PLA+舵机", joint: "SG90 直驱" },
          { id: "m5", name: "腕关节", type: "Rotation", material: "PLA+舵机", joint: "SG90 直驱" },
          { id: "m6", name: "夹具", type: "Gripper", material: "PLA", joint: "开合" }
        ],
        mechanicalConnections: [
          { source: "m1", target: "m2", type: "旋转副", hardware: "M3 螺丝 + 舵机轴" },
          { source: "m2", target: "m3", type: "旋转副", hardware: "M3 螺丝 + 舵机轴" },
          { source: "m3", target: "m4", type: "旋转副", hardware: "M3 螺丝 + 舵机轴" },
          { source: "m4", target: "m5", type: "旋转副", hardware: "M3 螺丝 + 舵机轴" },
          { source: "m5", target: "m6", type: "固定副", hardware: "M3 螺丝" }
        ],
        assembly: [
          { id: "a1", name: "基座组装", description: "将基座打印件与腰关节舵机固定。" },
          { id: "a2", name: "大臂组装", description: "连接肩、肘关节并预埋舵机线。" },
          { id: "a3", name: "夹具组装", description: "安装腕关节与夹具舵机。" },
          { id: "a4", name: "电控安装", description: "固定 ESP32 与 PCA9685，布置走线。" }
        ],
        instructionPreamble: "本方案为六自由度机械臂的完整搭建指南，共 4 个阶段，建议总耗时 3-4 小时。",
        instructionSteps: [
          { title: "准备与打印", subSteps: [{ title: "打印结构件", detail: "按 printSettings 打印基座、连杆与夹具，检查公差。" }, { title: "备料", detail: "清点舵机、螺丝、杜邦线等物料。" }] },
          { title: "机械装配", subSteps: [{ title: "组装基座", detail: "将腰关节舵机装入基座，拧紧 M3 螺丝。" }, { title: "组装手臂", detail: "依次连接肩、肘、腕关节，确保转动顺畅。" }] },
          { title: "电气接线", subSteps: [{ title: "连接电源", detail: "12V 适配器接入降压模块，输出 5V 至 PCA9685。" }, { title: "连接控制", detail: "ESP32 与 PCA9685 之间接 I2C 与供电，舵机接入 PWM 通道。" }] },
          { title: "调试与运行", subSteps: [{ title: "上电自检", detail: "检查舵机中立位与行程。" }, { title: "运行演示", detail: "加载固件，执行抓取演示。" }] }
        ],
        notes: ["舵机需外置电源，切勿从 ESP32 直接取电。", "所有打印件建议使用 PLA 并开启填充加固。"]
      };
    }
  },
  {
    match: [/灯|lamp|light|照明/i],
    build() {
      return {
        projectName: "智能触控台灯",
        projectDescription: "带触控调光与自动感应的智能台灯，深夜靠近自动点亮。",
        nodes: [
          { id: "n1", name: "ESP32-C3 开发板", category: "Microcontroller", type: "ESP32-C3", pins: "GPIO", dimensions: "25 x 18 x 3 mm", material: "PCB", printSettings: null },
          { id: "n2", name: "LED 灯珠模组", category: "Light", type: "COB LED 12V", pins: "DC", dimensions: "100 x 20 x 8 mm", material: "铝基板", printSettings: null },
          { id: "n3", name: "电容触摸按键", category: "Sensor", type: "TP223", pins: "GPIO", dimensions: "15 x 15 x 2 mm", material: "PCB", printSettings: null },
          { id: "n4", name: "人体红外传感器", category: "Sensor", type: "HC-SR501", pins: "GPIO", dimensions: "32 x 25 x 12 mm", material: "PCB", printSettings: null },
          { id: "n5", name: "MOS 调光驱动", category: "Driver", type: "IRF520 Module", pins: "PWM", dimensions: "30 x 20 x 5 mm", material: "PCB", printSettings: null }
        ],
        wiring: [
          { source: "n1", target: "n3", sourcePin: "GPIO4", targetPin: "OUT", protocol: "GPIO", voltage: "3.3V" },
          { source: "n1", target: "n4", sourcePin: "GPIO5", targetPin: "OUT", protocol: "GPIO", voltage: "3.3V" },
          { source: "n1", target: "n5", sourcePin: "GPIO2(PWM)", targetPin: "SIG", protocol: "PWM", voltage: "3.3V" },
          { source: "n5", target: "n2", sourcePin: "OUT+", targetPin: "LED+", protocol: "Power", voltage: "12V" }
        ],
        electricalConnections: [
          { source: "ESP32-C3 开发板", target: "电容触摸按键", type: "触摸检测", protocol: "GPIO", voltage: "3.3V" },
          { source: "ESP32-C3 开发板", target: "人体红外传感器", type: "人体感应", protocol: "GPIO", voltage: "3.3V" },
          { source: "ESP32-C3 开发板", target: "MOS 调光驱动", type: "PWM 调光", protocol: "PWM", voltage: "3.3V" },
          { source: "MOS 调光驱动", target: "LED 灯珠模组", type: "供电", protocol: "DC", voltage: "12V" }
        ],
        parts: [
          { partType: "mcu", name: "ESP32-C3 开发板", type: "Microcontroller", category: "控制核心", qty: 1, price: 15, description: "低成本 Wi-Fi 主控。" },
          { partType: "misc", name: "COB LED 灯珠模组", type: "Light Module", category: "光源", qty: 1, price: 12, description: "12V 高亮灯珠。" },
          { partType: "sensor", name: "TP223 触摸模块", type: "Touch Sensor", category: "传感器", qty: 1, price: 3, description: "电容触摸输出。" },
          { partType: "sensor", name: "HC-SR501 人体感应", type: "PIR Sensor", category: "传感器", qty: 1, price: 4, description: "红外人体感应。" },
          { partType: "power", name: "IRF520 调光模块", type: "MOSFET Driver", category: "驱动", qty: 1, price: 4, description: "PWM 调光。" }
        ],
        mechanical: [{ id: "m1", name: "灯架（打印件）", type: "Structure", material: "PLA", joint: "固定" }],
        mechanicalConnections: [{ source: "m1", target: "m1", type: "固定副", hardware: "M3 螺丝" }],
        assembly: [{ id: "a1", name: "外壳组装", description: "固定灯珠与驱动板于灯架。" }],
        instructionPreamble: "智能台灯搭建指南，约 1-2 小时。",
        instructionSteps: [
          { title: "装配", subSteps: [{ title: "固定灯架", detail: "将灯珠模组固定于灯架。" }] },
          { title: "接线", subSteps: [{ title: "连接驱动", detail: "按接线图连接 ESP32 与调光模块。" }] },
          { title: "调试", subSteps: [{ title: "烧录固件", detail: "烧录固件并校准触摸灵敏度。" }] }
        ],
        notes: ["灯珠供电需 12V 适配器。"]
      };
    }
  },
  {
    match: [/天气|weather|气象|温湿/i],
    build() {
      return {
        projectName: "桌面气象站",
        projectDescription: "实时显示温度、湿度、气压与空气质量的小型桌面气象站，支持网页查看历史曲线。",
        nodes: [
          { id: "n1", name: "ESP32 开发板", category: "Microcontroller", type: "ESP32 DevKit", pins: "GPIO", dimensions: "55 x 28 x 15 mm", material: "PCB", printSettings: null },
          { id: "n2", name: "BME280 温压传感器", category: "Sensor", type: "BME280", pins: "I2C", dimensions: "20 x 15 x 3 mm", material: "PCB", printSettings: null },
          { id: "n3", name: "OLED 显示屏", category: "Display", type: "SSD1306 0.96\"", pins: "I2C", dimensions: "27 x 27 x 2 mm", material: "PCB", printSettings: null },
          { id: "n4", name: "粉尘传感器", category: "Sensor", type: "PMS5003", pins: "UART", dimensions: "50 x 38 x 21 mm", material: "金属壳", printSettings: null }
        ],
        wiring: [
          { source: "n1", target: "n2", sourcePin: "SDA/SCL", targetPin: "SDA/SCL", protocol: "I2C", voltage: "3.3V" },
          { source: "n1", target: "n3", sourcePin: "SDA/SCL", targetPin: "SDA/SCL", protocol: "I2C", voltage: "3.3V" },
          { source: "n1", target: "n4", sourcePin: "UART0", targetPin: "TX/RX", protocol: "UART", voltage: "5V" }
        ],
        electricalConnections: [
          { source: "ESP32 开发板", target: "BME280 温压传感器", type: "数据采集", protocol: "I2C", voltage: "3.3V" },
          { source: "ESP32 开发板", target: "OLED 显示屏", type: "显示", protocol: "I2C", voltage: "3.3V" },
          { source: "ESP32 开发板", target: "粉尘传感器", type: "数据采集", protocol: "UART", voltage: "5V" }
        ],
        parts: [
          { partType: "mcu", name: "ESP32 开发板", type: "Microcontroller", category: "控制核心", qty: 1, price: 28, description: "数据汇聚与上传。" },
          { partType: "sensor", name: "BME280", type: "Sensor", category: "传感器", qty: 1, price: 8, description: "温湿度气压。" },
          { partType: "display", name: "OLED 0.96 寸", type: "Display", category: "显示", qty: 1, price: 10, description: "本地实时显示。" },
          { partType: "sensor", name: "PMS5003 粉尘传感器", type: "Sensor", category: "传感器", qty: 1, price: 60, description: "PM2.5 检测。" }
        ],
        mechanical: [{ id: "m1", name: "外壳（打印件）", type: "Enclosure", material: "PLA", joint: "卡扣" }],
        mechanicalConnections: [],
        assembly: [{ id: "a1", name: "外壳与固定", description: "安装传感器与屏幕于外壳。" }],
        instructionPreamble: "桌面气象站搭建指南，约 1-2 小时。",
        instructionSteps: [
          { title: "装配外壳", subSteps: [{ title: "打印外壳", detail: "打印外壳并预留通风口。" }] },
          { title: "接线", subSteps: [{ title: "I2C 总线", detail: "传感器与屏幕接入同一 I2C 总线。" }] },
          { title: "固件", subSteps: [{ title: "烧录与校准", detail: "烧录固件，校准传感器偏差。" }] }
        ],
        notes: ["粉尘传感器建议外置进气口。"]
      };
    }
  },
  {
    match: [/小车|rover|car|坦克|robot car/i],
    build() {
      return {
        projectName: "Wi-Fi 遥控小车",
        projectDescription: "基于 ESP32 的 Wi-Fi 遥控小车，支持网页摇杆控制与超声波避障。",
        nodes: [
          { id: "n1", name: "ESP32 开发板", category: "Microcontroller", type: "ESP32 DevKit", pins: "GPIO", dimensions: "55 x 28 x 15 mm", material: "PCB", printSettings: null },
          { id: "n2", name: "L298N 电机驱动", category: "Driver", type: "L298N", pins: "IN1-4", dimensions: "43 x 43 x 27 mm", material: "PCB+散热片", printSettings: null },
          { id: "n3", name: "直流减速电机 x2", category: "Motor", type: "GA12-N20", pins: "DC", dimensions: "25 x 20 x 15 mm", material: "金属", printSettings: null },
          { id: "n4", name: "超声波传感器", category: "Sensor", type: "HC-SR04", pins: "GPIO", dimensions: "45 x 20 x 15 mm", material: "PCB", printSettings: null },
          { id: "n5", name: "7.4V 锂电池", category: "Power", type: "2S LiPo 1500mAh", pins: "XT60", dimensions: "70 x 36 x 18 mm", material: "锂聚合物", printSettings: null }
        ],
        wiring: [
          { source: "n1", target: "n2", sourcePin: "GPIO12-15", targetPin: "IN1-4", protocol: "GPIO", voltage: "3.3V" },
          { source: "n2", target: "n3", sourcePin: "OUT1-4", targetPin: "M1/M2", protocol: "Power", voltage: "7.4V" },
          { source: "n1", target: "n4", sourcePin: "GPIO16/17", targetPin: "TRIG/ECHO", protocol: "GPIO", voltage: "5V" },
          { source: "n5", target: "n2", sourcePin: "XT60", targetPin: "12V/5V", protocol: "Power", voltage: "7.4V" }
        ],
        electricalConnections: [
          { source: "ESP32 开发板", target: "L298N 电机驱动", type: "方向控制", protocol: "GPIO", voltage: "3.3V" },
          { source: "L298N 电机驱动", target: "直流减速电机 x2", type: "驱动", protocol: "DC", voltage: "7.4V" },
          { source: "ESP32 开发板", target: "超声波传感器", type: "测距", protocol: "GPIO", voltage: "5V" }
        ],
        parts: [
          { partType: "mcu", name: "ESP32 开发板", type: "Microcontroller", category: "控制核心", qty: 1, price: 28, description: "主控与 Wi-Fi。" },
          { partType: "motor", name: "L298N 驱动板", type: "Motor Driver", category: "驱动", qty: 1, price: 12, description: "双 H 桥驱动。" },
          { partType: "motor", name: "GA12-N20 减速电机", type: "DC Motor", category: "执行器", qty: 2, price: 15, description: "带减速箱。" },
          { partType: "sensor", name: "HC-SR04 超声波", type: "Ultrasonic", category: "传感器", qty: 1, price: 3, description: "避障测距。" },
          { partType: "power", name: "2S 锂电池 1500mAh", type: "LiPo", category: "电源", qty: 1, price: 45, description: "整机供电。" },
          { partType: "structural", name: "底盘（打印件）", type: "3D Print", category: "结构", qty: 1, price: 12, description: "双层底盘。" }
        ],
        mechanical: [
          { id: "m1", name: "底盘", type: "Chassis", material: "PLA", joint: "螺丝" },
          { id: "m2", name: "左轮组", type: "Wheel", material: "橡胶+轴", joint: "电机直驱" },
          { id: "m3", name: "右轮组", type: "Wheel", material: "橡胶+轴", joint: "电机直驱" }
        ],
        mechanicalConnections: [
          { source: "m1", target: "m2", type: "固定副", hardware: "M3 螺丝" },
          { source: "m1", target: "m3", type: "固定副", hardware: "M3 螺丝" }
        ],
        assembly: [{ id: "a1", name: "底盘组装", description: "安装电机、驱动板与传感器。" }],
        instructionPreamble: "Wi-Fi 遥控小车搭建指南，约 2-3 小时。",
        instructionSteps: [
          { title: "底盘", subSteps: [{ title: "安装电机", detail: "固定减速电机并接线。" }] },
          { title: "电控", subSteps: [{ title: "连接驱动", detail: "按接线图连接 L298N。" }] },
          { title: "软件", subSteps: [{ title: "烧录固件", detail: "烧录 Wi-Fi 遥控固件并配置 AP。" }] }
        ],
        notes: ["电池与主控需共地。"]
      };
    }
  },
  {
    match: [/风扇|fan|散热/i],
    build() {
      return {
        projectName: "智能温控风扇",
        projectDescription: "根据环境温度自动调速的桌面风扇，也可手动三档控制。",
        nodes: [
          { id: "n1", name: "ESP8266/ESP32", category: "Microcontroller", type: "ESP32", pins: "GPIO", dimensions: "55 x 28 x 15 mm", material: "PCB", printSettings: null },
          { id: "n2", name: "NTC 温度传感器", category: "Sensor", type: "10K NTC", pins: "ADC", dimensions: "10 x 5 x 3 mm", material: "热敏电阻", printSettings: null },
          { id: "n3", name: "PWM 风扇 12V", category: "Motor", type: "120mm 4-pin", pins: "PWM", dimensions: "120 x 120 x 25 mm", material: "工程塑料", printSettings: null },
          { id: "n4", name: "MOS 开关模块", category: "Driver", type: "IRF520", pins: "PWM", dimensions: "30 x 20 x 5 mm", material: "PCB", printSettings: null }
        ],
        wiring: [
          { source: "n1", target: "n2", sourcePin: "ADC0", targetPin: "OUT", protocol: "ADC", voltage: "3.3V" },
          { source: "n1", target: "n4", sourcePin: "GPIO2", targetPin: "SIG", protocol: "PWM", voltage: "3.3V" },
          { source: "n4", target: "n3", sourcePin: "OUT+", targetPin: "12V", protocol: "Power", voltage: "12V" }
        ],
        electricalConnections: [
          { source: "ESP8266/ESP32", target: "NTC 温度传感器", type: "温度采集", protocol: "ADC", voltage: "3.3V" },
          { source: "ESP8266/ESP32", target: "MOS 开关模块", type: "调速", protocol: "PWM", voltage: "3.3V" },
          { source: "MOS 开关模块", target: "PWM 风扇 12V", type: "供电", protocol: "DC", voltage: "12V" }
        ],
        parts: [
          { partType: "mcu", name: "ESP32 开发板", type: "Microcontroller", category: "控制核心", qty: 1, price: 28, description: "主控。" },
          { partType: "sensor", name: "10K NTC 热敏电阻", type: "Thermistor", category: "传感器", qty: 1, price: 1, description: "测温。" },
          { partType: "motor", name: "120mm PWM 风扇", type: "Fan", category: "执行器", qty: 1, price: 25, description: "4 线 PWM 调速风扇。" },
          { partType: "power", name: "IRF520 模块", type: "MOSFET", category: "驱动", qty: 1, price: 4, description: "PWM 功率驱动。" }
        ],
        mechanical: [{ id: "m1", name: "风扇支架（打印件）", type: "Structure", material: "PLA", joint: "螺丝" }],
        mechanicalConnections: [],
        assembly: [{ id: "a1", name: "支架安装", description: "固定风扇与主控。" }],
        instructionPreamble: "智能温控风扇指南，约 1 小时。",
        instructionSteps: [
          { title: "支架", subSteps: [{ title: "打印支架", detail: "打印风扇支架。" }] },
          { title: "接线", subSteps: [{ title: "连接驱动", detail: "按接线图接线。" }] },
          { title: "固件", subSteps: [{ title: "烧录", detail: "烧录温控固件。" }] }
        ],
        notes: ["风扇需 12V 电源。"]
      };
    }
  }
];

function genericBuild(prompt) {
  const first = prompt.trim().replace(/[，。！？、\n]+$/, "");
  const name = first.length > 18 ? first.slice(0, 18) + "…" : (first || "我的创意项目");
  return {
    projectName: name,
    projectDescription: "根据你的描述生成的硬件项目方案：" + (prompt.slice(0, 160) || "自定义项目"),
    nodes: [
      { id: "n1", name: "主控开发板", category: "Microcontroller", type: "ESP32 DevKit", pins: "GPIO", dimensions: "55 x 28 x 15 mm", material: "PCB", printSettings: null },
      { id: "n2", name: "电源模块", category: "Power", type: "MP1584", pins: "VIN/VOUT", dimensions: "22 x 17 x 5 mm", material: "PCB", printSettings: null },
      { id: "n3", name: "执行/传感模块", category: "Module", type: "按需选型", pins: "GPIO/I2C", dimensions: "30 x 20 x 10 mm", material: "PCB", printSettings: null }
    ],
    wiring: [
      { source: "n1", target: "n2", sourcePin: "VIN/GND", targetPin: "IN", protocol: "Power", voltage: "5V" },
      { source: "n1", target: "n3", sourcePin: "GPIO", targetPin: "SIG", protocol: "GPIO", voltage: "3.3V" }
    ],
    electricalConnections: [
      { source: "主控开发板", target: "电源模块", type: "供电", protocol: "DC", voltage: "5V" },
      { source: "主控开发板", target: "执行/传感模块", type: "控制", protocol: "GPIO", voltage: "3.3V" }
    ],
    parts: [
      { partType: "mcu", name: "主控开发板", type: "Microcontroller", category: "控制核心", qty: 1, price: 28, description: "项目主控。" },
      { partType: "power", name: "电源模块", type: "Buck", category: "电源", qty: 1, price: 5, description: "系统供电。" },
      { partType: "misc", name: "传感器/执行器", type: "Module", category: "功能模块", qty: 2, price: 10, description: "按需求选型。" },
      { partType: "connector", name: "杜邦线/端子", type: "Connector", category: "连接", qty: 1, price: 6, description: "连接用。" }
    ],
    mechanical: [{ id: "m1", name: "外壳（打印件）", type: "Enclosure", material: "PLA", joint: "卡扣" }],
    mechanicalConnections: [],
    assembly: [{ id: "a1", name: "整机装配", description: "固定主控与模块，完成接线。" }],
    instructionPreamble: "通用项目搭建指南，约 1-2 小时。",
    instructionSteps: [
      { title: "备料", subSteps: [{ title: "清点物料", detail: "按物料清单准备元件。" }] },
      { title: "装配", subSteps: [{ title: "安装结构", detail: "固定结构件。" }] },
      { title: "接线", subSteps: [{ title: "连接电路", detail: "按接线图完成连接。" }] },
      { title: "调试", subSteps: [{ title: "上电测试", detail: "上电并验证功能。" }] }
    ],
    notes: ["请根据实际选型调整参数。"]
  };
}

export function demoDoc(prompt) {
  const p = String(prompt || "");
  for (const t of demoTemplates) {
    if (t.match.some((re) => re.test(p))) return t.build(p);
  }
  return genericBuild(p);
}

// ---------- LLM 生成（配置了真实 API 时） ----------
const SCHEMA_HINT = `你是硬件设计助手。根据用户的描述，输出一个 JSON 对象（不要输出任何其他文字），字段如下：
{
  "projectName": "项目名称（中文）",
  "projectDescription": "一句话项目描述（中文）",
  "nodes": [{"id":"n1","name":"元件名","category":"Microcontroller|Sensor|Power|Actuator|Display|Structure|Driver|Module","type":"型号","pins":"引脚说明","dimensions":"尺寸","material":"材料","printSettings":"打印参数或 null"}],
  "wiring": [{"source":"n1","target":"n2","sourcePin":"","targetPin":"","protocol":"I2C|PWM|UART|GPIO|Power","voltage":"3.3V|5V|12V"}],
  "electricalConnections": [{"source":"元件名","target":"元件名","type":"连接说明","protocol":"","voltage":""}],
  "parts": [{"partType":"mcu|sensor|power|motor|display|structural|connector|misc","name":"零件名","type":"类型","category":"分类","qty":数量,"price":预估单价,"description":"用途说明"}],
  "mechanical": [{"id":"m1","name":"结构件名","type":"类型","material":"材料","joint":"连接方式"}],
  "mechanicalConnections": [{"source":"m1","target":"m2","type":"旋转副|固定副","hardware":"五金件"}],
  "assembly": [{"id":"a1","name":"步骤名","description":"说明"}],
  "instructionPreamble": "组装指南引言",
  "instructionSteps": [{"title":"阶段名","subSteps":[{"title":"步骤名","detail":"详细说明"}]}],
  "notes": ["注意事项"]
}
要求：节点数量 3-8 个；接线与电气连接真实合理；零件数量 4-10 个；价格用人民币估算；所有字段齐全；不要使用 Markdown 代码块。`;

export async function llmDoc(prompt, cfg) {
  const system = SCHEMA_HINT;
  const user = `用户的想法：${prompt}\n\n请输出完整 JSON。`;
  const res = await callLLM({
    provider: cfg.provider,
    apiKey: cfg.apiKey,
    baseUrl: cfg.baseUrl,
    model: cfg.model,
    system,
    user,
    maxTokens: 8192,
    timeoutMs: 45000,
  });
  const doc = extractJson(res.text);
  if (!doc.projectName) throw new Error("模型输出缺少 projectName 字段");
  return normalizeDoc(doc, prompt);
}

function normalizeDoc(doc, prompt) {
  const d = doc || {};
  return {
    projectName: String(d.projectName || "未命名项目"),
    projectDescription: String(d.projectDescription || ""),
    originalPrompt: String(prompt || ""),
    readme: String(d.readme || ""),
    nodes: Array.isArray(d.nodes) ? d.nodes.map((n, i) => ({ id: n.id || "n" + (i + 1), name: String(n.name || ""), category: n.category || "Module", type: n.type || "", pins: Array.isArray(n.pins) ? n.pins : (n.pins == null ? null : [String(n.pins)]), dimensions: n.dimensions || null, material: n.material || null, printSettings: n.printSettings ?? null })) : [],
    wiring: Array.isArray(d.wiring) ? d.wiring : [],
    electricalConnections: Array.isArray(d.electricalConnections) ? d.electricalConnections : [],
    parts: Array.isArray(d.parts) ? d.parts.map((p, i) => ({ partType: p.partType || "misc", name: String(p.name || "零件" + (i + 1)), type: p.type || "", category: p.category || "", qty: Number(p.qty) || 1, price: Number(p.price) || 0, description: String(p.description || "") })) : [],
    mechanical: Array.isArray(d.mechanical) ? d.mechanical : [],
    mechanicalConnections: Array.isArray(d.mechanicalConnections) ? d.mechanicalConnections : [],
    assembly: Array.isArray(d.assembly) ? d.assembly : [],
    instructionPreamble: String(d.instructionPreamble || ""),
    instructionSteps: Array.isArray(d.instructionSteps) ? d.instructionSteps : [],
    notes: Array.isArray(d.notes) ? d.notes : [],
    userImages: [],
    renderPosition: null,
    visualSnaps: []
  };
}

// ---------- 前端渲染兜底：零件/节点必须带 id、estimatedCost、quantity ----------
function enrichDoc(doc) {
  if (!doc || typeof doc !== "object") return doc;
  const priceOfNode = (n) => {
    const pn = n.productName || n.name;
    if (Array.isArray(doc.parts)) {
      const m = doc.parts.find((p) => p.name === pn);
      if (m) return Number(m.price) || 0;
    }
    return Number(n.price ?? n.estimatedCost ?? 0);
  };
  if (Array.isArray(doc.nodes)) {
    doc.nodes = doc.nodes.map((n, i) => {
      if (!n || typeof n !== "object") return n;
      const price = priceOfNode(n);
      return { ...n, id: n.id || "n" + (i + 1), estimatedCost: Number.isFinite(price) ? price : 0, quantity: Number(n.quantity ?? 1) || 1 };
    });
  }
  if (Array.isArray(doc.parts)) {
    doc.parts = doc.parts.map((p, i) => {
      if (!p || typeof p !== "object") return p;
      const price = Number(p.price ?? p.estimatedCost ?? 0);
      return { ...p, id: p.id || "p" + (i + 1), estimatedCost: Number.isFinite(price) ? price : 0, quantity: Number(p.qty ?? p.quantity ?? 1) || 1 };
    });
  }
  if (Array.isArray(doc.instructionSteps)) {
    doc.instructionSteps = doc.instructionSteps.map((s, i) => {
      if (!s || typeof s !== "object") return s;
      const subSteps = Array.isArray(s.subSteps) ? s.subSteps.map((v, j) => {
        if (!v || typeof v !== "object") return { title: String(v || ""), id: "s" + (i + 1) + "." + (j + 1), partIds: [] };
        return { ...v, id: v.id || "s" + (i + 1) + "." + (j + 1), partIds: Array.isArray(v.partIds) ? v.partIds : [] };
      }) : [];
      return { ...s, id: s.id || "step" + (i + 1), tools: Array.isArray(s.tools) ? s.tools : [], subSteps };
    });
  }
  if (doc.instructionPreamble !== undefined && doc.instructionPreamble !== null) {
    const p = doc.instructionPreamble;
    if (typeof p === "string") {
      doc.instructionPreamble = { text: p, tools: [], assumptions: [] };
    } else if (typeof p === "object") {
      doc.instructionPreamble = { ...p, tools: Array.isArray(p.tools) ? p.tools : [], assumptions: Array.isArray(p.assumptions) ? p.assumptions : [] };
    }
  }
  return doc;
}

export async function generateDoc(prompt, cfg) {
  // 主配置 + 备用 key 列表：按顺序尝试，全部失败才回退内置演示模板
  const list = [];
  if (cfg && cfg.provider && cfg.apiKey) list.push({ provider: cfg.provider, apiKey: cfg.apiKey, baseUrl: cfg.baseUrl, model: cfg.model });
  for (const b of (cfg && Array.isArray(cfg.backups) ? cfg.backups : [])) {
    if (b && b.provider && b.apiKey) list.push({ provider: b.provider, apiKey: b.apiKey, baseUrl: b.baseUrl, model: b.model });
  }
  if (list.length === 0) return enrichDoc(demoDoc(prompt));
  let lastErr = "";
  for (const c of list) {
    try {
      return enrichDoc(await llmDoc(prompt, c));
    } catch (e) {
      lastErr = String(e.message || "模型调用失败");
    }
  }
  // 全部模型失败回退演示模式，保证可用
  const doc = demoDoc(prompt);
  doc._llmFallback = lastErr;
  return enrichDoc(doc);
}
