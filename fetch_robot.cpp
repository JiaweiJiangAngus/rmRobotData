#include "fetch_robot.h"

int main() {
    fs::create_directories("data");
    CURL* curl = curl_easy_init();
    std::string response;

    if (!curl) {
        std::cerr << "CURL init failed\n";
        return 1;
    }

    curl_easy_setopt(curl, CURLOPT_URL, "https://rm-static.djicdn.com/live_json/robot_data.json");
    curl_easy_setopt(curl, CURLOPT_USERAGENT, "Mozilla/5.0");
    curl_easy_setopt(curl, CURLOPT_WRITEFUNCTION, WriteCallback);
    curl_easy_setopt(curl, CURLOPT_WRITEDATA, &response);

    CURLcode res = curl_easy_perform(curl);
    curl_easy_cleanup(curl);

    if (res != CURLE_OK) {
        std::cerr << "Request failed: " << curl_easy_strerror(res) << "\n";
        return 1;
    }

    try {
        json data = json::parse(response);

        if (!data.contains("zones") || !data["zones"].is_array()) {
            std::cerr << "No 'zones' array in JSON\n";
            return 1;
        }

        std::map<std::string, std::ofstream> files;

        for (auto& zone : data["zones"]) {
            std::string zoneName = get_string(zone, "zoneName");
            if (zoneName.empty() || !is_target_zone(zoneName)) continue; // 只保留目标 zone

            if (!zone.contains("teams") || !zone["teams"].is_array()) continue;

            if (files.find(zoneName) == files.end()) {
                size_t pos = zoneName.find("部赛区");
                if (pos != std::string::npos) {
                    zoneName.replace(pos, std::string("部赛区").length(), "部分区赛");
                }
                pos = zoneName.find("站");
                if (pos != std::string::npos) {
                    zoneName.replace(pos, std::string("站").length(), "站3V3联盟赛");
                }
                files[zoneName] = std::ofstream("data/zone_" + zoneName + ".txt");
            }

            std::ofstream& out = files[zoneName];
            out << "Zone Name: " << zoneName << "\n\n";

            for (auto& team : zone["teams"]) {
                std::string college = get_string(team, "collegeName");
                std::string teamName = get_string(team, "name");
                if (teamName.find("INNOVATOR") != std::string::npos || teamName.find("CREATOR") != std::string::npos) continue;
                out << "Team: " << college << " (" << teamName << ")\n";

                if (!team.contains("robots") || !team["robots"].is_array()) continue;

                for (auto& r : team["robots"]) {
                    std::string type_name = get_string(r, "type");
                    out << "  Type: " << type_name << "\n";
                    int robot_type = robot_ID(type_name);
                    switch (robot_type) {
                        case 0 :
                            out << "  EA Small Hit Rate: " << get_string(r, "eaSmallHitRate") << "\n";
                            out << "  EAG Hurt: " << get_string(r, "eagHurt") << "\n";
                            out << "  EA KDA: " << get_string(r, "eaKDA") << "\n";
                            out << "  EA gkda Score: " << get_string(r, "eagKdaScore") << "\n";
                            out << "  Big Energy: " << get_string(r, "matchLargeEnergyActRoundsAvg") << "\n";
                            out << "  GK Damage: " << get_string(r, "gkDamage") << "\n";
                            out << "  G Kill Count: " << get_string(r, "gKillCount") << "\n";
                            break;
                        case 1 :
                            out << "  EA Big Hit Rate: " << get_string(r, "eaBigHitRate") << "\n";
                            out << "  EA KDA: " << get_string(r, "eaKDA") << "\n";
                            out << "  EA gkda Score: " << get_string(r, "eagKdaScore") << "\n";
                            out << "  GK Damage: " << get_string(r, "gkDamage") << "\n";
                            out << "  G Kill Count: " << get_string(r, "gKillCount") << "\n";
                            out << "  EA Snipe Count: " << get_string(r, "eaSnipeCnt") << "\n";
                            break;
                        case 2 :
                            out << "  EA KDA: " << get_string(r, "eaKDA") << "\n";
                            out << "  EA gkda Score: " << get_string(r, "eagKdaScore") << "\n";
                            out << "  EA Exchange Economy: " << get_string(r, "eaExchangeEcon") << "\n";
                            out << "  A Mine Time: " << get_string(r, "avgMineTime") << "\n";
                            out << "  A Mine Difficulty: " << get_string(r, "avgMineDiff") << "\n";
                            break;
                        case 3 :
                            out << "  EA Small Hit Rate: " << get_string(r, "eaSmallHitRate") << "\n";
                            out << "  EAG Hurt: " << get_string(r, "eagHurt") << "\n";
                            out << "  EA KDA: " << get_string(r, "eaKDA") << "\n";
                            out << "  EA gkda Score: " << get_string(r, "eagKdaScore") << "\n";
                            out << "  GK Damage: " << get_string(r, "gkDamage") << "\n";
                            out << "  G Kill Count: " << get_string(r, "gKillCount") << "\n";
                            out << "  A Shoot Number: " << get_string(r, "avgShootNum") << "\n";
                            break;
                        case 4 :
                            out << "  EA Small Hit Rate: " << get_string(r, "eaSmallHitRate") << "\n";
                            out << "  EAG Hurt: " << get_string(r, "eagHurt") << "\n";
                            out << "  EA KDA: " << get_string(r, "eaKDA") << "\n";
                            out << "  EA gkda Score: " << get_string(r, "eagKdaScore") << "\n";
                            out << "  GK Damage: " << get_string(r, "gkDamage") << "\n";
                            out << "  G Kill Count: " << get_string(r, "gKillCount") << "\n";
                            break;
                        case 5 :
                            out << "  EA KDA: " << get_string(r, "eaKDA") << "\n";
                            out << "  EA gkda Score: " << get_string(r, "eagKdaScore") << "\n";
                            out << "  GK Damage: " << get_string(r, "gkDamage") << "\n";
                            out << "  G Kill Count: " << get_string(r, "gKillCount") << "\n";
                            out << "  ET Outpost Count: " << get_string(r, "etDartOutpostCnt") << "\n";
                            out << "  ET Fixed Count: " << get_string(r, "etDartFixedCnt") << "\n";
                            out << "  ET Random Fixed Count: " << get_string(r, "etDartRDFixCnt") << "\n";
                            out << "  ET Random Move Count: " << get_string(r, "etDartRDMoveCnt") << "\n";
                            break;
                        case 6 :
                            out << "  EA Marker Time: " << get_string(r, "eaRadarMarkerTime") << "\n";
                            out << "  EA Debuff Damage: " << get_string(r, "eaRadarDebuffDmg") << "\n";
                            break;
                        defalut :
                            break;
                    }
                    out << "  ------------------------\n";
                }
                out << "\n";
            }
            out << "========================\n\n";
        }

        // 关闭所有文件
        for (auto& kv : files) kv.second.close();

        std::cout << "已按指定 zoneName 分文件保存完毕\n";

    } catch (const std::exception& e) {
        std::cerr << "JSON parse error: " << e.what() << "\n";
        return 1;
    }

    return 0;
}
