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

        std::ofstream csv("temp_table.csv");
        const char bom[] = { (char)0xEF, (char)0xBB, (char)0xBF };
        csv.write(bom, 3);

        csv << "赛区,学校,战队,兵种";
        for (const auto& k : headerKeys) csv << "," << get_chinese_header(k);
        csv << "\n";
        for (const auto& r : data) {
            csv<< "," << r.zone << "," << r.college << "," << r.teamName << "," << get_chinese_header(r.type);
            for (const auto& k : headerKeys) {
                csv << ",";
                if (r.stats.count(k)) csv << r.stats.at(k);
            }
            csv << "\n";
        }
        csv.close();

        std::cout << ">> 正在启动界面 (默认排序: " << (defaultSort.empty() ? "无" : defaultSort) << ")...\n";
        
        // 传递第3个参数：默认排序列名
        std::string cmd = "python3 view_table.py temp_table.csv \"" + title + "\" \"" + defaultSort + "\"";
        #ifdef _WIN32
        cmd = "python view_table.py temp_table.csv \"" + title + "\" \"" + defaultSort + "\"";
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
            if (line.find("Zone Name:") == 0) currZone = trim(line.substr(10));
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

    // 模式1：赛区 + 兵种查询
    void search_by_zone_type(const std::string& zoneKey, const std::string& typeKey) {
        std::string targetType = translate_type(typeKey);
        std::vector<RobotData> res;
        for (const auto& r : database) {
            bool z = (zoneKey == "ALL") || (r.zone.find(zoneKey) != std::string::npos);
            bool t = (targetType == "ALL") || (r.type == targetType);
            if (z && t) res.push_back(r);
        }
        // 获取默认排序键
        std::string defaultSort = get_default_sort_key(targetType);
        export_and_show(res, zoneKey + " " + typeKey, defaultSort);
    }

    // 模式2：搜学校/队伍 (全兵种)
    void search_by_team(const std::string& key) {
        std::vector<RobotData> res;
        for (const auto& r : database) {
            if (r.college.find(key) != std::string::npos || r.teamName.find(key) != std::string::npos) {
                res.push_back(r);
            }
        }
        // 搜学校时，默认排序可以传空，或者传一个通用的比如"对敌伤害量"
        // 因为 Python 端会在每个兵种 Tab 里尝试排序，如果该兵种没有这个指标，会自动忽略
        export_and_show(res, key + " 数据汇总", "对敌伤害量");
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
        std::cout << "模式 1: [赛区] [兵种]\n";
        std::cout << "模式 2: [学校/队名]\n";
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

        if (args.size() >= 2) {
            // 两个参数 -> 模式1 (赛区 + 兵种)
            mgr.search_by_zone_type(args[0], args[1]);
        } else {
            // 一个参数 -> 模式2 (搜学校)
            mgr.search_by_team(args[0]);
        }
    }
    return 0;
}