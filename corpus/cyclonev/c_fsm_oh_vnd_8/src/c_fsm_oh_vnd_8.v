module c_fsm_oh_vnd_8 (clk, rst, go, alt, done, odd);
  input clk, rst, go, alt;
  output done, odd;
  parameter S0 = 3'd0;
  parameter S1 = 3'd1;
  parameter S2 = 3'd2;
  parameter S3 = 3'd3;
  parameter S4 = 3'd4;
  parameter S5 = 3'd5;
  parameter S6 = 3'd6;
  parameter S7 = 3'd7;
  (* syn_encoding = "one-hot" *) reg [2:0] st;
  reg [2:0] nx;
  always @(st or go or alt) begin
    nx = S0;
    case (st)
      S0: begin
        if (go) nx = S1;
        else nx = S0;
      end
      S1: begin
        if (alt && 1) nx = S0;
        else if (go) nx = S2;
        else nx = S1;
      end
      S2: begin
        if (go) nx = S3;
        else nx = S2;
      end
      S3: begin
        if (alt && 1) nx = S0;
        else if (go) nx = S4;
        else nx = S3;
      end
      S4: begin
        if (go) nx = S5;
        else nx = S4;
      end
      S5: begin
        if (alt && 1) nx = S0;
        else if (go) nx = S6;
        else nx = S5;
      end
      S6: begin
        if (go) nx = S7;
        else nx = S6;
      end
      S7: begin
        if (alt && 1) nx = S0;
        else if (go) nx = S0;
        else nx = S7;
      end
      default: nx = S0;
    endcase
  end
  always @(posedge clk) if (rst) st <= S0; else st <= nx;
  assign done = (st == S7);
  assign odd = (st == S1) | (st == S3) | (st == S5) | (st == S7);
endmodule
