#include <iostream>
#include <fstream>
#include <string>
#include <vector>
#include <filesystem>
#include <map>
#include <set>
#include <algorithm>
#include <sstream>
#include <iomanip>

namespace fs = std::filesystem;

// ==========================================
// 1. 基础结构与工具
// ==========================================
struct RobotData {
    std::string zone;
    std::string college;
    std::string teamName;
    std::string type;
    std::map<std::string, double> stats; 
};

std::string trim(const std::string& str) {
    size_t first = str.find_first_not_of(" \t\r\n");
    if (std::string::npos == first) return "";
    size_t last = str.find_last_not_of(" \t\r\n");
    return str.substr(first, (last - first + 1));
}

double parse_double(std::string str) {
    try {
        str = trim(str);
        if (str.empty() || str == "null" || str == "nan") return 0.0;
        return std::stod(str);
    } catch (...) { return 0.0; }
}

std::string translate_type(const std::string& input) {
    if (input == "步兵") return "Infantry";
    if (input == "英雄") return "Hero";
    if (input == "工程") return "Sapper";
    if (input == "哨兵") return "Guard";
    if (input == "无人机" || input == "飞手") return "Airplane";
    if (input == "飞镖") return "Dart";
    if (input == "雷达") return "Radar";
    return input;
}

// 辅助函数：判断一个字符串是否是兵种名称 (用于区分输入意图)
bool is_robot_type(const std::string& input) {
    std::string t = translate_type(input);
    static std::set<std::string> types = {
        "Infantry", "Hero", "Sapper", "Guard", "Airplane", "Dart", "Radar"
    };
    return types.count(t);
}
// ==========================================
// 2. 翻译与默认排序配置
// ==========================================

// 核心字典：英文Key -> 中文列名
std::string get_chinese_header(const std::string& key) {
    static std::map<std::string, std::string> dict = {
        // 兵种
        {"Infantry", "步兵"},
        {"Hero", "英雄"},
        {"Sapper", "工程"},
        {"Airplane", "无人机"},
        {"Guard", "哨兵"},
        {"Dart", "飞镖"},
        {"Radar", "雷达"},

        // 通用
        {"EA Small Hit Rate", "小弹丸命中率"},
        {"EA Big Hit Rate", "大弹丸命中率"},
        {"EAG Hurt", "对敌伤害量"},
        {"EA KDA", "KDA"},
        {"KDA_Kills", "场均击杀数"},
        {"KDA_Deaths", "场均死亡数"},
        {"KDA_Assists", "场均助攻数"},
        {"EA gkda Score", "KDA得分"},
        {"GK Damage", "建筑伤害"},
        {"G Kill Count", "击杀数"},
        {"A Shoot Number", "场均发弹量"},
        
        // 英雄专用
        {"EA Snipe Count", "部署命中次数"},
        
        // 工程专用
        {"A Mine Time", "平均兑矿时间(s)"},
        {"A Mine Difficulty", "兑矿难度系数"},
        {"EA Exchange Economy", "局均兑换经济数"},
        
        // 能量机关 (大符/小符)
        {"Big Energy", "大能量机关平均激活环数"},
        
        // 飞镖
        {"ET Outpost Count", "累计命中前哨站数"},
        {"ET Fixed Count", "累计命中固定靶数"},
        {"ET Random Fixed Count", "累计随机固定靶数"},
        {"ET Random Move Count", "累计随机移动靶数"},
        
        // 雷达
        {"EA Marker Time", "双倍易伤时间"},
        {"EA Debuff Damage", "额外伤害"}
    };
    if (dict.count(key)) return dict[key];
    if (key.find("HitRate") != std::string::npos) return key + "(命中率)";
    return key;
}

// 核心逻辑：根据兵种返回“默认排序的中文列名”
std::string get_default_sort_key(const std::string& type_eng) {
    if (type_eng == "Infantry" || type_eng == "Guard" || type_eng == "Airplane") 
        return "小弹丸命中率";
    if (type_eng == "Hero") 
        return "大弹丸命中率";
    if (type_eng == "Sapper") 
        return "局均经济";
    if (type_eng == "Dart") 
        return "随机移动靶";
    if (type_eng == "Radar") 
        return "易伤时间";
    return "";
}

// ==========================================
// 3. 数据管理器
// ==========================================
class DataManager {
private:
    std::vector<RobotData> database;
    std::set<std::string> knownZones; // 【新增】存储所有已知的赛区名
    // 通用导出CSV函数
    void export_and_show(const std::vector<RobotData>& data, const std::string& title, const std::string& defaultSort) {
        if (data.empty()) {
            std::cout << ">> 未找到数据。\n";
            return;
        }

        // 收集列名
        std::set<std::string> keys;
        for (const auto& r : data) for (const auto& kv : r.stats) keys.insert(kv.first);
        std::vector<std::string> headerKeys(keys.begin(), keys.end());

        std::ofstream csv("bin/temp_table.csv");
        const char bom[] = { (char)0xEF, (char)0xBB, (char)0xBF };
        csv.write(bom, 3);

        csv << "赛区,学校,战队,兵种";
        for (const auto& k : headerKeys) csv << "," << get_chinese_header(k);
        csv << "\n";
        for (const auto& r : data) {
            csv<< r.zone << "," << r.college << "," << r.teamName << "," << get_chinese_header(r.type);
            for (const auto& k : headerKeys) {
                csv << ",";
                if (r.stats.count(k)) csv << r.stats.at(k);
            }
            csv << "\n";
        }
        csv.close();

        std::cout << ">> 正在启动界面 (默认排序: " << (defaultSort.empty() ? "无" : defaultSort) << ")...\n";
        
        // 传递第3个参数：默认排序列名
        std::string cmd = "python3 view_table.py bin/temp_table.csv \"" + title + "\" \"" + defaultSort + "\"";
        #ifdef _WIN32
        cmd = "python view_table.py bin/temp_table.csv \"" + title + "\" \"" + defaultSort + "\"";
        #endif
        system(cmd.c_str());
    }

public:
    void load_data(const std::string& dirPath) {
        database.clear();
        if (!fs::exists(dirPath)) return;
        for (const auto& entry : fs::directory_iterator(dirPath)) {
            if (entry.path().extension() == ".txt") parse_file(entry.path().string());
        }
    }

    void parse_file(const std::string& filepath) {
        std::ifstream file(filepath);
        std::string line, currZone, currCollege, currTeam, currType;
        std::map<std::string, double> currStats;
        auto save = [&]() {
            if (!currType.empty() && !currCollege.empty()) 
                database.push_back({currZone, currCollege, currTeam, currType, currStats});
            currType = ""; currStats.clear();
        };
        while (std::getline(file, line)) {
            line = trim(line);
            if (line.empty()) continue;
            if (line.find("Zone Name:") == 0) {
                currZone = trim(line.substr(10));
                knownZones.insert(currZone);
            }
            else if (line.find("Team:") == 0) {
                save();
                std::string content = trim(line.substr(5));
                size_t p1 = content.find('('), p2 = content.find(')');
                if (p1 != std::string::npos && p2 != std::string::npos) {
                    currCollege = trim(content.substr(0, p1));
                    currTeam = content.substr(p1 + 1, p2 - p1 - 1);
                } else { currCollege = content; currTeam = ""; }
            } else if (line.find("Type:") != std::string::npos) {
                save();
                currType = trim(line.substr(line.find(':') + 1));
            } else if (line.find("---") != std::string::npos || line.find("===") != std::string::npos) save();
            else {
                size_t colon = line.find(':');
                if (colon != std::string::npos && !currType.empty()) {
                    if (line.find("EA KDA") != std::string::npos) {
                        std::string kda_str = trim(line.substr(colon + 1));
                        float kills=0, assists=0, deaths=0;
                        sscanf(kda_str.c_str(), "%f/%f/%f", &kills, &deaths, &assists);
                        currStats["KDA_Kills"] = kills;
                        currStats["KDA_Assists"] = assists;
                        currStats["KDA_Deaths"] = deaths;
                    } else {
                        currStats[trim(line.substr(0, colon))] = parse_double(line.substr(colon + 1));
                    }
                }
            }
        }
        save();
    }

    bool is_zone_keyword(const std::string& key) {
        if (key == "全部" || key == "所有" || key == "ALL" || key == "全部赛区") return true;
        // 只要已知的赛区名包含用户输入的关键词，就认为是赛区 (例如输入"南部"匹配"南部赛区")
        for (const auto& z : knownZones) {
            if (z.find(key) != std::string::npos) return true;
        }
        return false;
    }

    // 模式1：赛区 + 兵种查询
    void search_by_zone_type(const std::string& zoneKey, const std::string& typeKey) {
        std::string targetType = translate_type(typeKey);
        std::vector<RobotData> res;
        for (const auto& r : database) {
            bool z = (zoneKey == "全部") || (r.zone.find(zoneKey) != std::string::npos);
            bool t = (targetType == "全部") || (r.type == targetType);
            if (z && t) res.push_back(r);
        }
        // 获取默认排序键
        std::string defaultSort = get_default_sort_key(targetType);
        export_and_show(res, zoneKey + " " + typeKey, defaultSort);
    }

    // 模式2 ：搜多个学校/队伍 (全兵种)
    void search_by_multiple_teams(const std::vector<std::string>& keywords) {
        std::vector<RobotData> res;
        for (const auto& r : database) {
            bool matched = false;
            // 检查该机器人是否匹配输入的任一关键词
            for (const auto& key : keywords) {
                if (r.college == key || r.teamName == key) {
                    matched = true;
                    break;
                }
            }
            if (matched) res.push_back(r);
        }
        // 多个队伍展示时，标题显示“多队伍数据汇总”，默认按对敌伤害排序
        export_and_show(res, "多队伍数据对比", "命中率");
    }

    // 模式3 ：指定赛区 + 搜多个学校/队伍
    void search_by_zone_and_teams(const std::string& zoneKey, const std::vector<std::string>& teams) {
        std::vector<RobotData> res;
        for (const auto& r : database) {
            // 先匹配赛区
            bool zoneMatch = (zoneKey == "ALL") || (r.zone.find(zoneKey) != std::string::npos);
            if (!zoneMatch) continue;

            // 再匹配队伍
            bool teamMatch = false;
            for (const auto& key : teams) {
                if (r.college == key || r.teamName == key) {
                    teamMatch = true; break;
                }
            }
            if (teamMatch) res.push_back(r);
        }
        export_and_show(res, zoneKey + " 多队伍数据", "小弹丸命中率");
    }
};

// ==========================================
// 4. 主程序
// ==========================================
int main() {
    #ifdef _WIN32
    system("chcp 65001");
    #endif

    DataManager mgr;
    std::cout << ">> 正在加载数据库...\n";
    mgr.load_data("data");
    std::cout << ">> 加载完成！\n";

    while (true) {
        std::cout << "\n========================================\n";
        std::cout << " RM 综合数据查询终端\n";
        std::cout << "========================================\n";
        std::cout << "用法 1 (排行): [赛区] [兵种]  \n";
        std::cout << "用法 2 (搜队): [队名1] [队名2]...\n";
        std::cout << "用法 3 (搜队): [赛区] [队名1]...\n";
        std::cout << "输入 exit 退出\n> ";

        std::string line;
        std::getline(std::cin, line);
        if (line == "exit") break;
        if (line.empty()) continue;

        std::stringstream ss(line);
        std::vector<std::string> args;
        std::string temp;
        while (ss >> temp) args.push_back(temp);

        if (args.empty()) continue;

        // === 智能判断逻辑 ===
        
        // 只有当参数恰好是2个，且第2个参数是合法的兵种名称时，才视为模式1
        if (args.size() == 2 && is_robot_type(args[1])) {
            std::string zone = args[0];
            if (zone == "全部" || zone == "全部赛区" || zone == "所有") zone = "ALL";
            mgr.search_by_zone_type(zone, args[1]);
        } 
        else {
            // 判定2：第一个参数是不是赛区？
            std::string firstArg = args[0];
            // 预处理关键字
            if (firstArg == "全部" || firstArg == "全部赛区" || firstArg == "所有") firstArg = "ALL";
            
            if (mgr.is_zone_keyword(firstArg)) {
                // 是赛区 -> 模式3：[赛区] [队1] [队2]
                std::string zoneKey = (firstArg == "ALL") ? "ALL" : args[0];
                
                // 提取剩下的参数作为队名
                std::vector<std::string> teamNames;
                for(size_t i = 1; i < args.size(); ++i) teamNames.push_back(args[i]);
                
                if (teamNames.empty()) {
                    std::cout << ">> 请输入至少一个队伍名称。\n";
                } else {
                    mgr.search_by_zone_and_teams(zoneKey, teamNames);
                }
            } 
            else {
                // 不是赛区 -> 模式2：所有参数都是队名
                mgr.search_by_multiple_teams(args);
            }
        }
    }
    return 0;
}